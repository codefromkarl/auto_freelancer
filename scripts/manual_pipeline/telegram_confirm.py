"""
Telegram 人工确认投标模块。

职责单一：发送候选项目确认消息 + 等待用户通过 inline keyboard 做出决策。
使用 getUpdates long polling，仅需出站 HTTPS，无需公网 IP。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class TelegramConfirm:
    """通过 Telegram inline keyboard 实现人工确认投标。"""

    def __init__(self, bot_token: str, chat_id: str, timeout: int = 300):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._session = requests.Session()
        # Telegram API 在国内需要代理；主进程可能已清除代理环境变量，
        # 因此从 TELEGRAM_PROXY 或常见代理变量中显式读取。
        proxy = os.getenv("TELEGRAM_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        if proxy:
            self._session.proxies = {"https": proxy, "http": proxy}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_candidates(self, candidates: List[Dict[str, Any]]) -> int:
        """发送候选项目列表 + inline keyboard，返回 message_id。"""
        text = self._build_message_text(candidates)
        keyboard = self._build_keyboard(candidates)

        resp = self._api_call("sendMessage", {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": keyboard},
        })
        message_id = resp["result"]["message_id"]
        logger.info("Confirmation message sent (message_id=%d)", message_id)
        return message_id

    def wait_for_decisions(
        self,
        message_id: int,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """轮询 getUpdates 等待用户点击按钮，返回被批准的候选列表。

        超时返回空列表（安全默认：不投标）。
        """
        decisions: Dict[int, str] = {}  # freelancer_id -> "approved"/"rejected"
        candidate_ids = [c["freelancer_id"] for c in candidates]

        # 消费掉 getUpdates 中已有的旧消息，获取初始 offset
        offset = self._flush_pending_updates()

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            poll_timeout = min(30, remaining)

            try:
                updates = self._get_updates(offset, poll_timeout)
            except Exception as exc:
                logger.warning("getUpdates error: %s", exc)
                time.sleep(2)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                callback = update.get("callback_query")
                if not callback:
                    continue

                # 仅处理来自目标消息的回调
                msg = callback.get("message", {})
                if msg.get("message_id") != message_id:
                    continue

                data = callback.get("data", "")
                self._answer_callback(callback["id"])

                if data == "approve_all":
                    for pid in candidate_ids:
                        decisions[pid] = "approved"
                    logger.info("User approved ALL candidates")
                    self._edit_final_status(message_id, candidates, decisions)
                    return candidates

                if data == "reject_all":
                    for pid in candidate_ids:
                        decisions[pid] = "rejected"
                    logger.info("User rejected ALL candidates")
                    self._edit_final_status(message_id, candidates, decisions)
                    return []

                if data.startswith("approve:"):
                    pid = int(data.split(":", 1)[1])
                    decisions[pid] = "approved"
                    logger.info("User approved candidate %d", pid)

                elif data.startswith("reject:"):
                    pid = int(data.split(":", 1)[1])
                    decisions[pid] = "rejected"
                    logger.info("User rejected candidate %d", pid)

                # 检查是否所有候选都已决策
                if all(pid in decisions for pid in candidate_ids):
                    approved = [
                        c for c in candidates
                        if decisions.get(c["freelancer_id"]) == "approved"
                    ]
                    self._edit_final_status(message_id, candidates, decisions)
                    return approved

        # 超时 → 安全默认：不投标
        logger.warning("Confirmation timed out after %ds, skipping all", self.timeout)
        self._edit_timeout(message_id, candidates)
        return []

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_message_text(candidates: List[Dict[str, Any]]) -> str:
        lines = ["🔔 *投标确认* — 以下项目待审批：\n"]
        for i, c in enumerate(candidates, 1):
            pid = c["freelancer_id"]
            title = (c.get("title") or "Untitled")[:50]
            score = c.get("ai_score", 0)
            budget_min = c.get("budget_minimum") or "?"
            budget_max = c.get("budget_maximum") or "?"
            currency = c.get("currency_code", "USD")
            amount = c.get("suggested_bid")
            period = c.get("estimated_hours")

            amount_str = f"${amount:.0f}" if amount else "自动"
            period_days = max(2, round(period / 6)) if period and period > 0 else 7
            period_str = f"{period_days}d"

            lines.append(
                f"*#{i}* `{pid}` {title}\n"
                f"  ⭐ {score:.1f} | 💰 {budget_min}-{budget_max} {currency}"
                f" | 💵 {amount_str} | ⏱ {period_str}\n"
            )
        lines.append("\n点击按钮确认或拒绝：")
        return "\n".join(lines)

    @staticmethod
    def _build_keyboard(
        candidates: List[Dict[str, Any]],
    ) -> List[List[Dict[str, str]]]:
        """构建 inline keyboard 布局。"""
        rows: List[List[Dict[str, str]]] = []
        # 第一行：全部确认 / 全部跳过
        rows.append([
            {"text": "✅ 全部确认", "callback_data": "approve_all"},
            {"text": "❌ 全部跳过", "callback_data": "reject_all"},
        ])
        # 每个候选一行：确认 / 拒绝
        for i, c in enumerate(candidates, 1):
            pid = c["freelancer_id"]
            short_title = (c.get("title") or "")[:20]
            rows.append([
                {"text": f"✅ #{i} {short_title}", "callback_data": f"approve:{pid}"},
                {"text": f"❌ #{i}", "callback_data": f"reject:{pid}"},
            ])
        return rows

    # ------------------------------------------------------------------
    # Telegram API helpers
    # ------------------------------------------------------------------

    def _api_call(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self._base_url}/{method}"
        resp = self._session.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description', data)}")
        return data

    def _get_updates(self, offset: int, poll_timeout: int) -> List[Dict]:
        """调用 getUpdates，使用 long polling。"""
        url = f"{self._base_url}/getUpdates"
        resp = self._session.post(url, json={
            "offset": offset,
            "timeout": poll_timeout,
            "allowed_updates": ["callback_query"],
        }, timeout=poll_timeout + 10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", [])

    def _flush_pending_updates(self) -> int:
        """消费掉所有已有的 updates，返回下一个 offset。"""
        try:
            url = f"{self._base_url}/getUpdates"
            resp = self._session.post(url, json={
                "offset": -1,
                "timeout": 0,
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            updates = data.get("result", [])
            if updates:
                return updates[-1]["update_id"] + 1
        except Exception:
            pass
        return 0

    def _answer_callback(self, callback_query_id: str) -> None:
        """应答 callback query，消除 Telegram 客户端加载动画。"""
        try:
            self._api_call("answerCallbackQuery", {
                "callback_query_id": callback_query_id,
            })
        except Exception as exc:
            logger.debug("answerCallbackQuery failed: %s", exc)

    def _edit_final_status(
        self,
        message_id: int,
        candidates: List[Dict[str, Any]],
        decisions: Dict[int, str],
    ) -> None:
        """编辑原消息，显示最终决策结果。"""
        lines = ["🔔 *投标确认* — 决策完成：\n"]
        for i, c in enumerate(candidates, 1):
            pid = c["freelancer_id"]
            title = (c.get("title") or "Untitled")[:50]
            status = decisions.get(pid, "pending")
            icon = "✅" if status == "approved" else "❌"
            lines.append(f"{icon} *#{i}* `{pid}` {title}")

        approved_count = sum(1 for v in decisions.values() if v == "approved")
        lines.append(f"\n共 {approved_count}/{len(candidates)} 个项目已批准投标。")

        self._safe_edit_message(message_id, "\n".join(lines))

    def _edit_timeout(
        self,
        message_id: int,
        candidates: List[Dict[str, Any]],
    ) -> None:
        """超时后编辑原消息。"""
        text = self._build_message_text(candidates)
        text += f"\n\n⏰ 已超时（{self.timeout}s），本轮全部跳过。"
        self._safe_edit_message(message_id, text)

    def _safe_edit_message(self, message_id: int, text: str) -> None:
        """安全地编辑消息，忽略错误。"""
        try:
            self._api_call("editMessageText", {
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": text[:4096],
                "parse_mode": "Markdown",
            })
        except Exception as exc:
            logger.debug("editMessageText failed: %s", exc)
