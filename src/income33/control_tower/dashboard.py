from __future__ import annotations

from html import escape
from typing import Any

from income33.control_tower.rate_based_bookkeeping_config import (
    rate_based_bookkeeping_auto_action_label,
    rate_based_bookkeeping_auto_confirm_message,
    rate_based_bookkeeping_auto_hint,
)


BOT_DISPLAY_GROUPS: list[tuple[str, str, int, int, int]] = [
    ("발송 봇 01-09", "sender", 1, 9, 0),
    ("신고 봇 01-09", "reporter", 1, 9, 9),
]

REPORTER_ONE_CLICK_CUSTOM_TYPE_FILTER_OPTIONS: tuple[str, ...] = (
    "ALL",
    "NONE",
    "가",
    "나",
    "다",
    "라",
    "마",
    "바",
    "사",
    "아",
)


def _build_html_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    header = "".join(f"<th>{escape(col)}</th>" for col in columns)
    body_parts: list[str] = []
    for row in rows:
        cells = "".join(
            f"<td>{row.get(col, '')}</td>"
            if col == "actions"
            else f"<td>{escape(str(row.get(col, '')))}</td>"
            for col in columns
        )
        body_parts.append(f"<tr>{cells}</tr>")

    body = "".join(body_parts) if body_parts else "<tr><td colspan='99'>No rows</td></tr>"
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _command_button(
    bot_id: str,
    command: str,
    label: str,
    css_class: str = "",
    confirm_message: str | None = None,
) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    safe_command = escape(command, quote=True)
    safe_label = escape(label)
    safe_class = escape(css_class, quote=True)
    confirm_attr = ""
    if confirm_message:
        safe_confirm = escape(confirm_message, quote=True)
        confirm_attr = f" onclick=\"return confirm('{safe_confirm}')\""
    return (
        f"<form method='post' action='/ui/bots/{safe_bot_id}/commands/{safe_command}' "
        "style='display:inline'>"
        f"<button class='{safe_class}' type='submit'{confirm_attr}>{safe_label}</button>"
        "</form>"
    )


def _submit_auth_code_form(bot_id: str) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    return (
        f"<form method='post' action='/ui/bots/{safe_bot_id}/auth-code' class='inline-form'>"
        "<input type='password' name='auth_code' placeholder='인증코드 입력' "
        "autocomplete='one-time-code' required />"
        "<button type='submit' class='auth'>인증코드 제출</button>"
        "</form>"
    )


def _all_bots_action_form(
    *,
    action: str,
    label: str,
    confirm_message: str,
    hint: str | None = None,
    extra_controls: str = "",
) -> str:
    safe_action = escape(action, quote=True)
    safe_label = escape(label)
    safe_confirm = escape(confirm_message, quote=True)
    hint_html = ""
    if hint:
        hint_html = f"<span class='hint'>{escape(hint)}</span>"
    return (
        f"<form method='post' action='{safe_action}' class='inline-form' style='display:inline'>"
        f"{extra_controls}"
        "<button type='submit' class='send' "
        f"onclick=\"return confirm('{safe_confirm}')\">"
        f"{safe_label}</button>"
        f"{hint_html}"
        "</form>"
    )


def _reporter_one_click_custom_type_filter_select() -> str:
    options_html = "".join(
        (
            f"<option value='{escape(option, quote=True)}' selected>{escape(option)}</option>"
            if option == "NONE"
            else f"<option value='{escape(option, quote=True)}'>{escape(option)}</option>"
        )
        for option in REPORTER_ONE_CLICK_CUSTOM_TYPE_FILTER_OPTIONS
    )
    return (
        "<label style='margin-right:6px'>자동조회 신고제출 유형 "
        "<select name='tax_doc_custom_type_filter'>"
        f"{options_html}"
        "</select></label>"
    )


def _global_bulk_actions_html() -> str:
    return " ".join(
        [
            _all_bots_action_form(
                action="/ui/commands/senders/send-expected-tax-amounts-all",
                label="전체 계산발송",
                confirm_message="sender 전체(01~09)에 계산발송을 큐잉할까요?",
                hint="sender 01~09 전체",
            ),
            _all_bots_action_form(
                action="/ui/commands/senders/send-simple-expense-rate-expected-tax-amounts-all",
                label="전체 단순경비율 목록발송",
                confirm_message="sender 전체(01~09)에 단순경비율 목록발송을 큐잉할까요?",
                hint="sender 01~09 전체",
            ),
            _all_bots_action_form(
                action="/ui/commands/senders/send-rate-based-bookkeeping-expected-tax-amounts-all",
                label="전체 경비율 장부발송",
                confirm_message="sender 전체(01~09)에 경비율 장부발송(자동조회)을 큐잉할까요?",
                hint=rate_based_bookkeeping_auto_hint(),
            ),
            _all_bots_action_form(
                action="/ui/commands/senders/stop-and-clear-active-all",
                label="sender 전체 중지+활성명령초기화",
                confirm_message="sender 전체(01~09) 활성명령을 실패처리하고 stop을 큐잉할까요?",
                hint="sender 01~09 stop + active clear",
            ),
            _all_bots_action_form(
                action="/ui/commands/reporters/submit-tax-reports-one-click-all",
                label="전체 자동조회 신고제출 실행",
                confirm_message="reporter 전체(01~09)에 자동조회 신고제출 실행을 큐잉할까요?",
                hint="SUBMIT_READY · 유형 NONE · 검토 NORMAL 전체조회 후 5분 반복 신고제출",
                extra_controls=_reporter_one_click_custom_type_filter_select(),
            ),
            _all_bots_action_form(
                action="/ui/commands/reporters/stop-and-clear-active-all",
                label="reporter 전체 중지+활성명령초기화",
                confirm_message="reporter 전체(01~09) 활성명령을 실패처리하고 stop을 큐잉할까요?",
                hint="reporter 01~09 stop + active clear",
            ),
        ]
    )


def _taxdoc_id_list_rate_based_bookkeeping_form(bot_id: str) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    safe_confirm = escape(rate_based_bookkeeping_auto_confirm_message(), quote=True)
    safe_label = escape(rate_based_bookkeeping_auto_action_label())
    safe_hint = escape(rate_based_bookkeeping_auto_hint())
    return (
        f"<form method='post' action='/ui/bots/{safe_bot_id}/rate-based-bookkeeping-send-list' "
        "class='inline-form' style='display:inline'>"
        "<button type='submit' class='send' "
        f"onclick=\"return confirm('{safe_confirm}')\">"
        f"{safe_label}</button>"
        f"<span class='hint'>{safe_hint}</span>"
        "</form>"
    )


def _taxdoc_id_list_tax_report_submit_form(bot_id: str) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    return (
        f"<form method='post' action='/ui/bots/{safe_bot_id}/tax-report-submit-list' "
        "class='inline-form advanced-action' style='display:inline'>"
        "<textarea name='tax_doc_ids' rows='2' cols='24' "
        "placeholder='고급 수동 신고준비 taxDocId 목록(쉼표/공백/줄바꿈)' required></textarea>"
        "<button type='submit' class='send' "
        "onclick=\"return confirm('붙여넣은 taxDocId 목록으로 수동 신고준비(담당자 배정+음수항목 보정)만 순차 실행할까요?')\">"
        "수동 신고준비(고급)</button>"
        "</form>"
    )


def _taxdoc_id_list_tax_report_one_click_submit_form(bot_id: str) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    action = f"/ui/bots/{safe_bot_id}/tax-report-one-click-submit-list"
    return (
        f"<form method='post' action='{action}' class='inline-form' style='display:inline'>"
        "<button type='submit' class='send' "
        "onclick=\"return confirm('실제 최종 신고제출입니다. 입력칸 없이 SUBMIT_READY/유형 NONE/검토 NORMAL 대상을 자동조회하고, 없으면 5분 대기 후 반복할까요?')\">"
        "자동조회 신고제출 실행</button>"
        "<span class='hint'>SUBMIT_READY · 유형 NONE · 검토 NORMAL 전체조회 후 5분 반복 신고제출</span>"
        "</form>"
        "<details class='advanced-action' style='display:inline'>"
        "<summary>고급: 수동 taxDocId 지정</summary>"
        f"<form method='post' action='{action}' class='inline-form' style='display:inline'>"
        "<textarea name='tax_doc_ids' rows='2' cols='24' "
        "placeholder='선택사항: 특정 taxDocId만 수동 신고제출(비우면 자동조회)'></textarea>"
        "<button type='submit' class='send' "
        "onclick=\"return confirm('입력한 taxDocId만 수동 신고제출합니다. 비어있으면 자동조회 모드로 실행됩니다. 진행할까요?')\">"
        "수동 ID목록 신고제출</button>"
        "</form>"
        "</details>"
    )


def _taxdoc_id_list_tax_report_one_click_status_check_form(bot_id: str) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    action = f"/ui/bots/{safe_bot_id}/tax-report-one-click-submit-status-check-list"
    return (
        f"<form method='post' action='{action}' class='inline-form' style='display:inline'>"
        "<button type='submit' class='send' "
        "onclick=\"return confirm('진행중 건 상태만 재확인합니다. 신고제출 PUT 없이 status GET만 실행할까요?')\">"
        "진행중 상태재확인</button>"
        "<span class='hint'>IN_PROGRESS 기록 기준, PUT 없이 status GET만 호출</span>"
        "</form>"
        "<details class='advanced-action' style='display:inline'>"
        "<summary>고급: 상태재확인 taxDocId 지정</summary>"
        f"<form method='post' action='{action}' class='inline-form' style='display:inline'>"
        "<textarea name='tax_doc_ids' rows='2' cols='24' "
        "placeholder='선택사항: 상태재확인 taxDocId 목록(비우면 진행중 로그에서 자동조회)'></textarea>"
        "<button type='submit' class='send' "
        "onclick=\"return confirm('입력한 건 상태만 재확인합니다. 신고제출 PUT 없이 status GET만 실행할까요?')\">"
        "수동 상태재확인</button>"
        "</form>"
        "</details>"
    )


def _bot_actions_html(bot_id: str) -> str:
    buttons = [
        _command_button(bot_id, "start", "시작"),
        _command_button(bot_id, "stop", "중지", "danger"),
        _command_button(bot_id, "restart", "재시작"),
        _command_button(bot_id, "open_login", "로그인 열기", "login"),
        _command_button(bot_id, "fill_login", "로그인 입력", "login"),
        _command_button(bot_id, "refresh_page", "새로고침", "refresh"),
    ]
    if bot_id.startswith("sender-"):
        buttons.append(
            _command_button(
                bot_id,
                "send_expected_tax_amounts",
                "계산발송",
                "send",
                "목록조회된 대상에 실제 계산발송을 요청하고 5분 후 자동 반복합니다. 진행할까요?",
            )
        )
        buttons.append(
            _command_button(
                bot_id,
                "send_simple_expense_rate_expected_tax_amounts",
                "단순경비율 목록발송",
                "send",
                "리뷰대기+단순경비율 목록 taxDocId를 조회한 뒤 순차 계산발송을 진행할까요?",
            )
        )
        buttons.append(_taxdoc_id_list_rate_based_bookkeeping_form(bot_id))
    if bot_id.startswith("reporter-"):
        buttons.append(_taxdoc_id_list_tax_report_submit_form(bot_id))
        buttons.append(_taxdoc_id_list_tax_report_one_click_submit_form(bot_id))
        buttons.append(_taxdoc_id_list_tax_report_one_click_status_check_form(bot_id))
    buttons.extend(
        [
            _command_button(bot_id, "login_done", "로그인 완료", "login-done"),
            _submit_auth_code_form(bot_id),
        ]
    )
    return " ".join(buttons)


def _build_fixed_slot_bot_sections(raw_bots: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    bot_map = {str(bot.get("bot_id", "")): bot for bot in raw_bots}
    sections: list[tuple[str, list[dict[str, Any]]]] = []

    for section_title, bot_type, start, end, pc_offset in BOT_DISPLAY_GROUPS:
        section_rows: list[dict[str, Any]] = []
        for slot in range(start, end + 1):
            bot_id = f"{bot_type}-{slot:02d}"
            row = dict(bot_map.get(bot_id) or {})
            if not row:
                row = {
                    "bot_id": bot_id,
                    "bot_type": bot_type,
                    "pc_id": f"pc-{slot + pc_offset:02d}",
                    "status": "connection_required",
                    "current_step": "접속필요",
                    "last_heartbeat_at": None,
                    "success_count": 0,
                    "failure_count": 0,
                }

            if not row.get("last_heartbeat_at"):
                row["status"] = row.get("status") or "connection_required"
                row["current_step"] = "접속필요"

            row["actions"] = _bot_actions_html(bot_id)
            section_rows.append(row)

        sections.append((section_title, section_rows))

    return sections


def render_dashboard_html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    agents = payload["agents"]
    bot_sections = _build_fixed_slot_bot_sections(payload["bots"])

    summary_items = "".join(
        f"<li><strong>{escape(str(key))}</strong>: {escape(str(value))}</li>" for key, value in summary.items()
    )
    global_bulk_actions_html = _global_bulk_actions_html()

    agent_columns = [
        "pc_id",
        "hostname",
        "ip_address",
        "status",
        "agent_version",
        "version_status",
        "git_head_short",
        "git_branch",
        "git_up_to_date",
        "git_dirty",
        "repo_path",
        "assigned_bot_ids",
        "last_heartbeat_at",
    ]
    bot_columns = [
        "bot_id",
        "bot_type",
        "pc_id",
        "status",
        "current_step",
        "active_command",
        "last_heartbeat_at",
        "success_count",
        "failure_count",
        "actions",
    ]

    agents_html = _build_html_table(agent_columns, agents)
    bot_sections_html = "".join(
        (
            "<div class='card'>"
            f"<h2>{escape(section_title)}</h2>"
            f"{_build_html_table(bot_columns, rows)}"
            "</div>"
        )
        for section_title, rows in bot_sections
    )

    return f"""
    <!doctype html>
    <html lang='ko'>
      <head>
        <meta charset='utf-8' />
        <meta http-equiv='refresh' content='5' />
        <title>33income Control Tower</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 24px; background: #f7f8fb; }}
          h1, h2 {{ color: #1f2937; }}
          .card {{ background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 18px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
          table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
          th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }}
          th {{ background: #f3f4f6; }}
          button {{ margin: 2px; padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; cursor: pointer; }}
          .inline-form {{ display: inline; margin-left: 6px; }}
          .inline-form input {{ width: 130px; margin-right: 4px; padding: 4px 6px; }}
          .inline-form textarea {{ width: 210px; margin-right: 4px; padding: 4px 6px; vertical-align: middle; }}
          button.danger {{ color: #b91c1c; }}
          button.login {{ background: #eef2ff; border-color: #818cf8; }}
          button.login-done {{ background: #ecfdf5; border-color: #34d399; }}
          button.refresh {{ background: #eff6ff; border-color: #60a5fa; }}
          button.send {{ background: #fef2f2; border-color: #f87171; color: #991b1b; font-weight: 600; }}
          button.auth {{ background: #fff7ed; border-color: #fb923c; }}
          code {{ background: #eef2ff; padding: 2px 6px; border-radius: 4px; }}
        </style>
      </head>
      <body>
        <h1>33income Control Tower</h1>
        <p>관제 대시보드 (Windows 런타임 기준)</p>
        <p><strong>연결 확인:</strong> 발송/신고 표가 01번부터 고정으로 표시됩니다. 아직 에이전트가 붙지 않은 봇은 <code>접속필요</code>로 보이고, 붙으면 <code>last_heartbeat_at</code> 시간이 갱신됩니다.</p>

        <div class='card'>
          <h2>요약</h2>
          <ul>{summary_items}</ul>
          <p>API: <code>/api/summary</code>, <code>/api/agents</code>, <code>/api/bots</code></p>
        </div>

        <div class='card'>
          <h2>전체 실행</h2>
          <p>각 버튼은 대상 봇 전체(발송 01~09 / 신고 01~09)에 동일 명령을 일괄 큐잉합니다.</p>
          {global_bulk_actions_html}
        </div>

        <div class='card'>
          <h2>Agents</h2>
          {agents_html}
        </div>

        {bot_sections_html}
      </body>
    </html>
    """
