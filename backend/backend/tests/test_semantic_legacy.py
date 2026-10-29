"""The legacy compatibility path must prove the complete expression."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.config import Settings
from aegisbank_api.main import create_app
from aegisbank_api.planning.contracts import PlanningRequest
from aegisbank_api.planning.rule import RuleBasedPlanner
from aegisbank_api.planning.semantic_legacy import allow_legacy


@pytest.fixture
def legacy(tmp_path):
    app = create_app(database_path=tmp_path / "legacy-proof.db", settings=Settings(_env_file=None))
    with TestClient(app):
        services = app.state.services
        yield RuleBasedPlanner(services.registry, services.repository), services.repository


@pytest.mark.parametrize(
    "instruction",
    [
        "我不想给妈妈转500元",
        "不是要给妈妈转500元",
        "给妈妈转500元别执行",
        "给妈妈转500元要等工资到账",
        "给妈妈转500元后给爸爸发条短信",
        "帮我准备妈妈的生日，预算1000元，还要订个餐厅",
        "上周账单",
        "请告诉我备用账户余额",
        "不想查余额",
        "挂失 CARD-9902 但先查我的账单",
        "查询我的本月账单然后发邮件",
    ],
)
def test_unknown_modifiers_cannot_escape_to_legacy_plan(legacy, instruction):
    planner, repository = legacy
    request = PlanningRequest(instruction=instruction)
    plan = planner.plan(request)
    assert plan.needs_clarification or not allow_legacy(request, plan, repository)


@pytest.mark.parametrize(
    "instruction",
    [
        "向 ACC-2002 转账 880 元",
        "从 ACC-3003 向 ACC-2002 转账 500 元",
        "再向 ACC-2002 转账500元",
        "转一万给ACC-2002",
        "给妈妈转500元",
        "查询我的本月账单",
        "生成我的账单报告",
        "生成我的年度账单",
        "有没有异常扣费",
        "帮我做订阅扣费分析",
        "我的订阅还有哪些要续费",
        "查看我的联系人",
        "查询余额",
        "我的订阅有哪些",
        "看看订阅",
        "查询理财产品",
        "我的理财持仓",
        "挂失 CARD-9902",
        "挂失尾号9902的卡 CARD-9902",
        "挂失尾号9902的卡和末四位9902的卡",
        "挂失 CARD-9902（card-9902）",
        "我的卡 CARD-8821 丢了，帮我挂失",
        "解挂 CARD-9902",
        "申请虚拟卡",
        "申请一张虚拟卡",
        "重置 CARD-8821 密码",
        "修改卡片密码 CARD-9902",
        "解锁交易限额 CARD-8821",
        "把 CARD-8821 的交易限额恢复到 8000 元",
        "把 CARD-8821 的信用卡额度调整到 8000 元",
        "把 CARD-8821 的还款日改到18号",
        "取消异常订阅",
        "帮我取消异常订阅",
        "把异常订阅取消掉",
        "取消那个异常订阅",
        "取消健身房月卡",
        "关闭云端影音订阅",
        "和妈妈、张三 AA 300",
        "分析我的账单并取消异常订阅",
        "准备妈妈的生日，预算1000元",
        "买入 2000 元 R2 理财",
        "买稳健短债理财产品 1000 元",
        "赎回 500 元",
        "赎回稳健短债300元",
        "明天给张三转500",
        "下周三给张三转500",
        "每月5号给张三转500",
        "查看我的定时任务",
        "卡丢了，帮我冻结 CARD-9902",
        "我的风险偏好是 R2",
        "把那个涨价的订阅退掉",
        "查一下我的账单",
        "赎回全部理财",
    ],
)
def test_known_complete_legacy_expressions_remain_available(legacy, instruction):
    planner, repository = legacy
    request = PlanningRequest(instruction=instruction)
    plan = planner.plan(request)
    assert not plan.needs_clarification, plan.clarification
    assert allow_legacy(request, plan, repository), (instruction, plan.model_dump())


def test_legacy_gate_verifies_amount_not_only_verb(legacy):
    planner, repository = legacy
    request = PlanningRequest(instruction="向 ACC-2002 转账500元")
    plan = planner.plan(request)
    plan.steps[0].arguments["amount_cny"] = 501
    assert not allow_legacy(request, plan, repository)


def test_legacy_bill_allows_matching_supplemental_account(legacy):
    planner, repository = legacy
    request = PlanningRequest(instruction="查询我的本月账单", arguments={"account_id": "ACC-1001"})
    plan = planner.plan(request)
    assert not plan.needs_clarification
    assert allow_legacy(request, plan, repository)


def test_supplemental_arguments_do_not_whitelist_an_unknown_full_instruction(legacy):
    planner, repository = legacy
    request = PlanningRequest(
        instruction="给妈妈转500元要等工资到账", arguments={"amount_cny": 500}
    )
    plan = planner.plan(request)
    assert plan.needs_clarification or not allow_legacy(request, plan, repository)


def test_semantic_api_checks_supplemental_arguments_without_bypassing_full_text(tmp_path):
    app = create_app(database_path=tmp_path / "supplemental.db", settings=Settings(_env_file=None))
    with TestClient(app) as client:
        valid = client.post(
            "/api/planner/plan",
            json={
                "instruction": "查询我的本月账单",
                "arguments": {"account_id": "ACC-1001"},
            },
        )
        assert valid.status_code == 200, valid.text
        assert valid.json()["status"] == "planned", valid.text
        for instruction, arguments in [
            ("查询我的本月账单", {"account_id": "ACC-2002"}),
            ("查询我的本月账单", {"unused": "unverified"}),
            ("给妈妈转500元要等工资到账", {"amount_cny": 500}),
        ]:
            response = client.post(
                "/api/planner/plan",
                json={
                    "instruction": instruction,
                    "arguments": arguments,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "needs_clarification", response.text
            assert not response.json()["plan"]["steps"]
