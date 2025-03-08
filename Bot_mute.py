import logging
import os
from typing import Dict, Any

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackContext,
    filters,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv


# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# Загрузка токена из .env
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")


def escape_markdown(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!\'"'
    return "".join(
        "\\" + char if char in escape_chars else char for char in text
    )


async def delete_message(context: CallbackContext) -> None:
    """Удаляет сообщение через 30 секунд."""
    job_data: Dict[str, Any] = context.job.data
    chat_id = job_data["chat_id"]
    message_id = job_data["message_id"]
    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
        logger.info(
            f"Сообщение {message_id} удалено из чата {chat_id}"
        )
    except Exception as e:
        logger.error(
            f"Ошибка при удалении сообщения {message_id} из чата "
            f"{chat_id}: {e}"
        )


async def start(update: Update, context: CallbackContext) -> None:
    """Обрабатывает вступление нового пользователя."""
    try:
        user = update.effective_user
        chat_id = update.effective_chat.id
        logger.info(
            f"Новый пользователь: {user.id} ({user.full_name}) в чате "
            f"{chat_id}"
        )

        chat_member = await context.bot.get_chat_member(
            chat_id=chat_id,
            user_id=user.id,
        )
        if chat_member.status == "creator":
            logger.info(
                f"Пользователь {user.id} — владелец чата, обработка не "
                f"требуется"
            )
            return

        logger.info(
            f"Ограничиваем права пользователя {user.id} в чате {chat_id}"
        )
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions={
                "can_send_messages": False,
                "can_send_media_messages": False,
                "can_send_other_messages": False,
                "can_add_web_page_previews": False,
            },
        )

        escaped_full_name = escape_markdown(user.full_name)
        message_text = (
            f"Привет, {escaped_full_name}\\! "
            "Чтобы иметь возможность писать, напиши администратору "
            "любое сообщение\\."
        )
        instruction_message = await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        logger.info(
            f"Сообщение отправлено: message_id="
            f"{instruction_message.message_id}"
        )

        context.job_queue.run_once(
            delete_message,
            30,
            data={
                "chat_id": chat_id,
                "message_id": instruction_message.message_id,
            },
        )
        logger.info(
            "Задача на удаление сообщения через 30 секунд установлена"
        )
    except Exception as e:
        logger.error(
            f"Ошибка для user_id {user.id} в chat_id {chat_id}: {e}"
        )


def main() -> None:
    """Запускает бота."""
    app = Application.builder().token(TOKEN).build()
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            start,
        )
    )
    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
