"""FastAPI entry point for the AegisBank trusted-agent MVP."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .audit import AuditService
from .banking.repository import BankingRepository
from .compensation import CompensationRegistry
from .config import Settings, get_settings
from .db import Database
from .executor import ToolExecutor
from .extensions import (
    activate_extensions,
    include_extension_routers,
    prepare_extensions,
    register_extension_tools,
    start_extension_background,
    stop_extension_background,
)
from .gateway import PermissionGateway, PermissionStore
from .planning.factory import build_planner, describe_planner
from .risk import DynamicRiskEngine
from .scenarios import (
    DEMO_USER,
    include_scenario_routers,
    prepare_persistence,
    register_scenario_tools,
    start_scenario_background,
    stop_scenario_background,
)
from .scheduler import DagScheduler, ExecutionFailedError, IntentError, ReauthError
from .schemas import (
    AgentRunRequest,
    ConfirmationRequest,
    PermissionUpdateRequest,
    ReconcileRequest,
)
from .services import CoreServices
from .tools.finance import build_registry
from .trust.action_envelope import EnvelopeError
from .trust.authz import AuthzError, AuthzService
from .trust.clarification import ClarificationError, ClarificationStore
from .trust.idempotency import (
    IdempotencyError,
    IdempotencyOutcome,
    IdempotencyStore,
)
from .trust.mfa import MfaService, OtpProvider
from .trust.readiness import NotReadyError, ReadinessService

ROLE_HEADER = "X-Aegis-Role"


def create_app(
    *,
    database_path: str | Path | None = None,
    settings: Settings | None = None,
    readiness_overrides: dict[str, Any] | None = None,
) -> FastAPI:
    config = settings or get_settings()
    if database_path is not None:
        config.database_path = Path(database_path)

    db = Database(config.database_path)
    bank_repository = BankingRepository(db)
    services = CoreServices(db=db, repository=bank_repository, settings=config)

    # Stage 2A runtime capabilities (multi-role, MFA, guarded execution).
    authz = AuthzService()
    mfa = MfaService([OtpProvider(config.demo_otp)], default_provider=config.mfa_default_provider)
    executor = ToolExecutor(db=db)
    compensation = CompensationRegistry()
    services.authz = authz
    services.mfa = mfa
    services.executor = executor
    services.compensation = compensation

    # Scenario modules own their schema, seed data, tools, intents and routes.
    scenario_modules = prepare_persistence(db, DEMO_USER)
    # Stage 2A cross-cutting capabilities are discovered the same way.
    extension_modules = prepare_extensions(db, DEMO_USER)

    registry = build_registry(bank_repository)
    services.registry = registry
    register_scenario_tools(services, scenario_modules)
    register_extension_tools(services, extension_modules)

    permission_store = PermissionStore(db)
    permission_store.seed(DEMO_USER, registry)
    gateway = PermissionGateway(
        registry=registry,
        permissions=permission_store,
        authz=authz,
    )
    services.gateway = gateway
    risk_engine = DynamicRiskEngine(bank_repository)
    audit = AuditService(db)
    services.audit = audit
    planner = build_planner(config, registry, bank_repository)
    scheduler = DagScheduler(
        planner=planner,
        registry=registry,
        gateway=gateway,
        risk_engine=risk_engine,
        db=db,
        audit=audit,
        confirmation_ttl_seconds=config.confirmation_ttl_seconds,
        demo_otp=config.demo_otp,
        mfa=mfa,
        executor=executor,
        compensation=compensation,
        circuit_breaker_threshold=config.circuit_breaker_threshold,
        circuit_breaker_window_seconds=config.circuit_breaker_window_seconds,
        circuit_breaker_lock_seconds=config.circuit_breaker_lock_seconds,
    )
    services.scheduler = scheduler
    activate_extensions(services, extension_modules)

    readiness = ReadinessService(
        db=db,
        audit=audit,
        repository=bank_repository,
        planner=planner,
        user_id=DEMO_USER,
        overrides=readiness_overrides,
    )
    idempotency = IdempotencyStore(db)
    clarifications = ClarificationStore(db)
    services.extras["readiness"] = readiness

    def ensure_ready() -> None:
        try:
            readiness.require_ready()
        except NotReadyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def resolve_role(role_header: str | None) -> str:
        try:
            return authz.normalize(role_header, default=config.authz_default_role)
        except AuthzError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def require_capability(role: str, capability: str) -> None:
        try:
            authz.require(role, capability)
        except AuthzError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def begin_idempotent(
        key: str | None, *, scope: str, request_hash: str
    ) -> IdempotencyOutcome | None:
        if not key:
            return None
        try:
            return idempotency.begin(scope=scope, key=key, request_hash=request_hash)
        except IdempotencyError as exc:
            raise HTTPException(
                status_code=409, detail={"code": exc.code, "message": str(exc)}
            ) from exc

    def release_idempotent(key: str | None, *, scope: str) -> None:
        if key:
            idempotency.release(scope=scope, key=key)

    def complete_idempotent(key: str | None, *, scope: str, response: dict[str, Any]) -> None:
        if key:
            idempotency.complete(scope=scope, key=key, response=response)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        start_scenario_background(services, scenario_modules)
        start_extension_background(services, extension_modules)
        try:
            yield
        finally:
            stop_extension_background(extension_modules)
            stop_scenario_background(scenario_modules)

    app = FastAPI(title=config.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.services = services
    app.state.readiness = readiness
    app.state.idempotency = idempotency
    app.state.authz = authz
    app.state.mfa = mfa
    app.state.executor = executor
    app.state.compensation = compensation
    app.state.extension_modules = extension_modules

    @app.exception_handler(EnvelopeError)
    async def envelope_error(_request: Request, exc: EnvelopeError):
        return JSONResponse(
            status_code=409, content={"detail": {"code": exc.code, "message": str(exc)}}
        )

    @app.exception_handler(AuthzError)
    async def authz_error(_request: Request, exc: AuthzError):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(NotReadyError)
    async def not_ready_error(_request: Request, exc: NotReadyError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(IdempotencyError)
    async def idempotency_error(_request: Request, exc: IdempotencyError):
        return JSONResponse(
            status_code=409, content={"detail": {"code": exc.code, "message": str(exc)}}
        )

    @app.middleware("http")
    async def protect_mutations(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                await run_in_threadpool(readiness.require_ready)
                role = authz.normalize(
                    request.headers.get(ROLE_HEADER), default=config.authz_default_role
                )
                if request.url.path.endswith("/run-due") or "/channels/im/" in request.url.path:
                    authz.require(role, "tool:execute")
                if request.url.path.endswith("/sandbox/demo/run") and not (
                    authz.allowed(role, "tool:execute") or authz.allowed(role, "ops:manage")
                ):
                    authz.require(role, "tool:execute")
                chunks = []
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 128_000:
                        return JSONResponse(status_code=413, content={"detail": "请求体超出上限。"})
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            except NotReadyError as exc:
                return JSONResponse(status_code=503, content={"detail": str(exc)})
            except AuthzError as exc:
                return JSONResponse(status_code=403, content={"detail": str(exc)})
        return await call_next(request)

    @app.get(f"{config.api_prefix}/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": config.app_name,
            "version": "0.1.0",
            "mode": "local-mvp",
            "planner": describe_planner(planner),
        }

    @app.get(f"{config.api_prefix}/health/ready")
    def health_ready() -> dict[str, Any]:
        return readiness.check()

    @app.get(f"{config.api_prefix}/banking/overview")
    def banking_overview(
        user_id: str = Query(default=DEMO_USER, max_length=64),
    ) -> dict[str, Any]:
        return bank_repository.overview(user_id).model_dump()

    @app.get(f"{config.api_prefix}/tools")
    def list_tools(user_id: str = Query(default=DEMO_USER, max_length=64)) -> dict[str, Any]:
        return {"tools": permission_store.list(user_id, registry)}

    @app.get(f"{config.api_prefix}/planner/info")
    def planner_info() -> dict[str, Any]:
        return {
            **describe_planner(planner),
            "tools": registry.names(),
            "structured_output": "ExecutionPlan/v1",
        }

    @app.post(f"{config.api_prefix}/planner/plan")
    def preview_plan(body: AgentRunRequest) -> dict[str, Any]:
        try:
            return scheduler.preview(
                user_id=body.user_id,
                instruction=body.instruction,
                tool_name=body.tool_name,
                arguments=body.arguments,
            )
        except IntentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{config.api_prefix}/permissions")
    def list_permissions(
        user_id: str = Query(default=DEMO_USER, max_length=64),
    ) -> dict[str, Any]:
        return {"permissions": permission_store.list(user_id, registry)}

    @app.put(f"{config.api_prefix}/permissions/{{tool_name}}")
    def update_permission(
        tool_name: str,
        body: PermissionUpdateRequest,
        user_id: str = Query(default=DEMO_USER, max_length=64),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = resolve_role(x_aegis_role)
        require_capability(role, "permission:manage")
        try:
            tool = registry.get(tool_name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="工具不存在。") from exc
        permission_store.set_granted(user_id, tool_name, body.granted)
        audit.record(
            event="permission_updated",
            user_id=user_id,
            instruction=f"{'授予' if body.granted else '撤回'} {tool_name} 权限",
            dag_path="permissions",
            tool_name=tool_name,
            arguments={"tool_name": tool_name, "granted": body.granted},
            result={"role": role, "permission": tool.metadata.permission},
            confirmation_state="permission_change",
            risk_level="green",
        )
        return {
            "tool_name": tool_name,
            "title": tool.metadata.title,
            "granted": body.granted,
        }

    @app.post(f"{config.api_prefix}/agent/run")
    def run_agent(
        body: AgentRunRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        ensure_ready()
        role = resolve_role(x_aegis_role)
        scope = "agent.run"
        request_hash = IdempotencyStore.request_hash(
            {"endpoint": "agent.run", "body": body.model_dump(), "role": role}
        )
        outcome = begin_idempotent(idempotency_key, scope=scope, request_hash=request_hash)
        if outcome is not None and outcome.state == "replay":
            return outcome.response or {}
        try:
            instruction = body.instruction
            if body.clarification_run_id:
                require_capability(role, "tool:execute")
                if body.tool_name or body.arguments:
                    raise ClarificationError("补充上下文时请仅提供补充文本。")
                instruction = clarifications.consume(
                    body.clarification_run_id,
                    user_id=body.user_id,
                    role=role,
                    answer=body.instruction,
                )
            result = scheduler.run(
                user_id=body.user_id,
                instruction=instruction,
                tool_name=body.tool_name,
                arguments=body.arguments,
                role=role,
            )
        except ClarificationError as exc:
            release_idempotent(idempotency_key, scope=scope)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CLARIFICATION_UNAVAILABLE",
                    "message": str(exc),
                },
            ) from exc
        except IntentError as exc:
            release_idempotent(idempotency_key, scope=scope)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            release_idempotent(idempotency_key, scope=scope)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        complete_idempotent(idempotency_key, scope=scope, response=result)
        return result

    @app.post(f"{config.api_prefix}/confirmations/{{action_id}}")
    def resolve_confirmation(
        action_id: str,
        body: ConfirmationRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        ensure_ready()
        role = resolve_role(x_aegis_role)
        scope = "confirmation"
        require_capability(role, "tool:execute")
        request_hash = IdempotencyStore.request_hash(
            {
                "endpoint": "confirmation",
                "action_id": action_id,
                "approved": body.approved,
                "mfa_provider": body.mfa_provider,
                "role": role,
            }
        )
        outcome = begin_idempotent(idempotency_key, scope=scope, request_hash=request_hash)
        if outcome is not None and outcome.state == "replay":
            return outcome.response or {}
        try:
            result = scheduler.confirm(
                user_id=DEMO_USER,
                action_id=action_id,
                approved=body.approved,
                reauth_token=body.reauth_token,
                role=role,
                mfa_provider=body.mfa_provider,
            )
        except EnvelopeError as exc:
            release_idempotent(idempotency_key, scope=scope)
            raise HTTPException(
                status_code=409, detail={"code": exc.code, "message": str(exc)}
            ) from exc
        except ReauthError as exc:
            release_idempotent(idempotency_key, scope=scope)
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ExecutionFailedError as exc:
            release_idempotent(idempotency_key, scope=scope)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except IntentError as exc:
            release_idempotent(idempotency_key, scope=scope)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        complete_idempotent(idempotency_key, scope=scope, response=result)
        return result

    @app.get(f"{config.api_prefix}/trust/circuit-breaker")
    def circuit_breaker_status(
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        require_capability(resolve_role(x_aegis_role), "trust:inspect")
        return scheduler.circuit_breaker_status()

    @app.post(f"{config.api_prefix}/trust/circuit-breaker/reset")
    def circuit_breaker_reset(
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = resolve_role(x_aegis_role)
        require_capability(role, "ops:manage")
        audit.record(
            event="circuit_breaker_reset",
            user_id=DEMO_USER,
            instruction="运维重置熔断器",
            dag_path="trust",
            tool_name="circuit_breaker",
            arguments={},
            result={"role": role},
            confirmation_state="ops",
            risk_level="green",
        )
        return scheduler.reset_circuit_breaker()

    @app.get(f"{config.api_prefix}/trust/actions/{{action_id}}")
    def trust_action(
        action_id: str,
        user_id: str = Query(default=DEMO_USER, max_length=64),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        require_capability(resolve_role(x_aegis_role), "trust:inspect")
        try:
            return scheduler.action_view(action_id, user_id=user_id)
        except IntentError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(f"{config.api_prefix}/trust/actions/{{action_id}}/reconcile")
    def trust_reconcile(
        action_id: str,
        body: ReconcileRequest,
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = resolve_role(x_aegis_role)
        require_capability(role, "ops:manage")
        try:
            return scheduler.reconcile(
                action_id=action_id,
                outcome=body.outcome,
                user_id=DEMO_USER,
                reason=body.reason,
            )
        except IntentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{config.api_prefix}/audit")
    def list_audit(
        limit: int = Query(default=50, ge=1, le=200),
        run_id: str | None = Query(default=None, max_length=128),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        require_capability(resolve_role(x_aegis_role), "audit:read")
        entries = audit.list(limit=limit, run_id=run_id)
        return {"entries": entries, "count": len(entries)}

    @app.get(f"{config.api_prefix}/audit/verify")
    def verify_audit(
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        require_capability(resolve_role(x_aegis_role), "audit:read")
        return audit.verify()

    include_scenario_routers(app, services, scenario_modules)
    include_extension_routers(app, services, extension_modules)
    return app


app = create_app()
