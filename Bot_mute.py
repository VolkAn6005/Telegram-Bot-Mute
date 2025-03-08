import logging
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv
import os

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Загрузка токена из .env
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

def escape_markdown(text):
    """Экранирует специальные символы для MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!\'"'
    return "".join("\\" + char if char in escape_chars else char for char in text)

async def delete_message(context):
    """Удаляет сообщение через 30 секунд."""
    job = context.job
    chat_id = job.data['chat_id']  # Исправлено: job.data вместо job.context
    message_id = job.data['message_id']  # Исправлено: job.data вместо job.context
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Сообщение {message_id} удалено из чата {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения {message_id} из чата {chat_id}: {e}")

async def start(update: Update, context):
    """Обрабатывает вступление нового пользователя."""
    try:
        user = update.effective_user
        chat_id = update.effective_chat.id
        logger.info(f"Новый пользователь: {user.id} ({user.full_name}) в чате {chat_id}")

        # Проверяем, является ли пользователь владельцем чата
        chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
        if chat_member.status == "creator":
            logger.info(f"Пользователь {user.id} — владелец чата, обработка не требуется")
            return

        # Ограничиваем права пользователя
        logger.info(f"Ограничиваем права пользователя {user.id} в чате {chat_id}")
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

        # Формируем и отправляем сообщение с Markdown
        escaped_full_name = escape_markdown(user.full_name)
        message_text = f"Привет, {escaped_full_name}\\! Чтобы иметь возможность писать, напиши администратору любое сообщение\\."
        instruction_message = await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        logger.info(f"Сообщение отправлено: message_id={instruction_message.message_id}")

        # Устанавливаем задачу на удаление сообщения через 30 секунд
        context.job_queue.run_once(
            delete_message,
            30,  # 30 секунд
            data={'chat_id': chat_id, 'message_id': instruction_message.message_id}
        )
        logger.info(f"Задача на удаление сообщения через 30 секунд установлена")

    except Exception as e:
        logger.error(f"Ошибка для user_id {user.id} в chat_id {chat_id}: {e}")

def main():
    """Запускает бота."""
    app = Application.builder().token(TOKEN).build()

    # Обработчик для новых участников чата
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, start))

    logger.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()