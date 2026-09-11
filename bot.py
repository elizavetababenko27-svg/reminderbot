import logging
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

user_checklists = {}
user_pending_reminders = {}


def build_checklist_keyboard(user_id: int):
    items = user_checklists.get(user_id, [])
    keyboard = []
    for idx, item in enumerate(items):
        status = "✅ " if item["done"] else "🔲 "
        text = f"{status} {item['text']}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"toggle_{idx}")])

    controls = []
    if items:
        controls.append(InlineKeyboardButton("🗑 Очистити виконані", callback_data="clean_done"))
        keyboard.append(controls)

    return InlineKeyboardMarkup(keyboard) if keyboard else None


def build_reminder_time_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("5 хв", callback_data="remind_time_5"),
            InlineKeyboardButton("15 хв", callback_data="remind_time_15"),
            InlineKeyboardButton("30 хв", callback_data="remind_time_30"),
        ],
        [
            InlineKeyboardButton("1 година", callback_data="remind_time_60"),
            InlineKeyboardButton("2 години", callback_data="remind_time_120"),
        ],
        [InlineKeyboardButton("❌ Скасувати", callback_data="cancel_remind")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📱 **Ваш мобільний планер**\n\n"
        "• **Напишіть будь-який текст** у чат, щоб додати його до чек-листу.\n"
        "• Натискайте на кнопки, щоб відмічати виконані справи.\n"
        "• Для нагадувань використовуйте команду `/remind <текст>`."
    )
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=build_checklist_keyboard(update.effective_user.id)
    )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if not text:
        return

    if user_id not in user_checklists:
        user_checklists[user_id] = []

    user_checklists[user_id].append({"text": text, "done": False})
    reply_markup = build_checklist_keyboard(user_id)
    await update.message.reply_text(
        f"➕ Додано: *{text}*\n\n📋 **Ваш чек-лист:**",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def show_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = user_checklists.get(user_id, [])
    if not items:
        await update.message.reply_text("📋 Ваш чек-лист порожній. Напишіть щось у чат!")
        return
    reply_markup = build_checklist_keyboard(user_id)
    await update.message.reply_text("📋 **Ваш чек-лист:**", parse_mode="Markdown", reply_markup=reply_markup)


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reminder_text = " ".join(context.args).strip()
    if not reminder_text:
        await update.message.reply_text("⚠️ Вкажіть текст нагадування.\nПриклад: `/remind Попити води`", parse_mode="Markdown")
        return

    user_pending_reminders[user_id] = reminder_text
    await update.message.reply_text(
        f"⏰ Оберіть, через скільки часу нагадати про:\n*\"{reminder_text}\"*",
        parse_mode="Markdown",
        reply_markup=build_reminder_time_keyboard(),
    )


async def alarm(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        chat_id=job.chat_id,
        text=f"⏰ **НАГАДУВАННЯ:**\n\n🔔 {job.data}",
        parse_mode="Markdown",
    )


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("toggle_"):
        idx = int(data.split("_")[1])
        items = user_checklists.get(user_id, [])
        if 0 <= idx < len(items):
            items[idx]["done"] = not items[idx]["done"]
            reply_markup = build_checklist_keyboard(user_id)
            await query.edit_message_reply_markup(reply_markup=reply_markup)

    elif data == "clean_done":
        items = user_checklists.get(user_id, [])
        user_checklists[user_id] = [item for item in items if not item["done"]]
        reply_markup = build_checklist_keyboard(user_id)
        if reply_markup:
            await query.edit_message_text("📋 **Оновлений чек-лист:**", parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await query.edit_message_text("🎉 Усі виконані справи видалено! Чек-лист порожній.")

    elif data.startswith("remind_time_"):
        minutes = int(data.split("_")[2])
        reminder_text = user_pending_reminders.get(user_id, "Нагадування")
        seconds = minutes * 60
        context.job_queue.run_once(alarm, seconds, chat_id=query.message.chat_id, data=reminder_text)
        user_pending_reminders.pop(user_id, None)

        time_label = f"{minutes} хв" if minutes < 60 else f"{minutes // 60} год"
        await query.edit_message_text(
            f"✅ **Нагадування встановлено!**\n\n📌 *{reminder_text}*\n⏳ Через: {time_label}",
            parse_mode="Markdown",
        )

    elif data == "cancel_remind":
        user_pending_reminders.pop(user_id, None)
        await query.edit_message_text("❌ Налаштування нагадування скасовано.")


def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN", "8765392289:AAEmBrLRy_QqKdfYYj0509VVms1MoH2ud6k")
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", show_checklist))
    application.add_handler(CommandHandler("remind", remind_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(handle_buttons))

    application.run_polling()


if __name__ == "__main__":
    main()
