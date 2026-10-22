"""FastAPI entry point for the AegisBank trusted-agent MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .audit import AuditService
from .banking.repository import BankingRepository
from .config import Settings, get_settings
from .db import Database
from .gateway import PermissionGateway, PermissionStore
from .planning.factory import build_planner, describe_planner
from .risk import DynamicRiskEngine
from .scheduler import DagScheduler, IntentError, ReauthError
from .schemas import AgentRunRequest, ConfirmationRequest, PermissionUpdateRequest
from .tools.finance import build_registry


def create_app(
    *,
    database_path: str | Path | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    config = settings or get_settings()
    if database_path is not None:
        config.database_path = Path(database_path)

    db = Database(config.database_path)
    bank_repository = BankingRepository(db)
    registry = build_registry(bank_repository)
    permission_store = PermissionStore(db)
    permission_store.seed("demo-user", registry)
    gateway = PermissionGateway(registry=registry, permissions=permission_store)
    risk_engine = DynamicRiskEngine(bank_repository)
    audit = AuditService(db)
    planner = build_planner(config, registry)
    scheduler = DagScheduler(
        planner=planner,
        registry=registry,
        gateway=gateway,
        risk_engine=risk_engine,
        db=db,
        audit=audit,
        confirmation_ttl_seconds=config.confirmation_ttl_seconds,
        demo_otp=config.demo_otp,
    )

    app = FastAPI(title=config.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get(f"{config.api_prefix}/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": config.app_name,
            "version": "0.1.0",
            "mode": "local-mvp",
            "planner": describe_planner(planner),
        }

    @app.get(f"{config.api_prefix}/banking/overview")
    def banking_overview(
        user_id: str = Query(default="demo-user", max_length=64),
    ) -> dict[str, Any]:
        return bank_repository.overview(user_id).model_dump()

    @app.get(f"{config.api_prefix}/tools")
    def list_tools(user_id: str = Query(default="demo-user", max_length=64)) -> dict[str, Any]:
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
        user_id: str = Query(default="demo-user", max_length=64),
    ) -> dict[str, Any]:
        return {"permissions": permission_store.list(user_id, registry)}

    @app.put(f"{config.api_prefix}/permissions/{{tool_name}}")
    def update_permission(
        tool_name: str,
        body: PermissionUpdateRequest,
        user_id: str = Query(default="demo-user", max_length=64),
    ) -> dict[str, Any]:
        try:
            tool = registry.get(tool_name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="工具不存在。") from exc
        permission_store.set_granted(user_id, tool_name, body.granted)
        return {
            "tool_name": tool_name,
            "title": tool.metadata.title,
            "granted": body.granted,
        }

    @app.post(f"{config.api_prefix}/agent/run")
    def run_agent(body: AgentRunRequest) -> dict[str, Any]:
        try:
            return scheduler.run(
                user_id=body.user_id,
                instruction=body.instruction,
                tool_name=body.tool_name,
                arguments=body.arguments,
            )
        except IntentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(f"{config.api_prefix}/confirmations/{{action_id}}")
    def resolve_confirmation(action_id: str, body: ConfirmationRequest) -> dict[str, Any]:
        try:
            return scheduler.confirm(
                user_id="demo-user",
                action_id=action_id,
                approved=body.approved,
                reauth_token=body.reauth_token,
            )
        except ReauthError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except IntentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(f"{config.api_prefix}/audit")
    def list_audit(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        entries = audit.list(limit=limit)
        return {"entries": entries, "count": len(entries)}

    @app.get(f"{config.api_prefix}/audit/verify")
    def verify_audit() -> dict[str, Any]:
        return audit.verify()

    return app


app = create_app()
