import datetime
import logging
import os
import re
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

user_reminders = {}
user_states = {}

# Словник для розпізнавання днів тижня (понеділок = 0, неділя = 6)
WEEKDAYS_MAP = {
    "понеділок": 0, "пон": 0, "пн": 0,
    "вівторок": 1, "вів": 1, "вт": 1,
    "середа": 2, "сер": 2, "ср": 2,
    "четвер": 3, "чт": 3,
    "п'ятниця": 4, "пятниця": 4, "пт": 4,
    "субота": 5, "суб": 5, "сб": 5,
    "неділя": 6, "нед": 6, "нд": 6,
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⏰ **Бот Нагадувань**\n\n"
        "• **Створити нагадування:** `/remind Назва 18:30`\n"
        "  *(можна додавати: `щодня`, `щотижня в понеділок, середу 10:00`)*\n"
        "• **Мої нагадування:** `/myreminders`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# --- НАГАДУВАННЯ (/remind) ---

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if not args:
        user_states[user_id] = {"step": "WAITING_FOR_TEXT"}
        await update.message.reply_text(
            "⏰ **Створення нагадування**\n\nВкажіть текст нагадування:",
            parse_mode="Markdown",
        )
        return

    full_text = " ".join(args)
    await parse_and_schedule_reminder(update, context, full_text)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id, {}).get("step")

    if state == "WAITING_FOR_TEXT":
        text = update.message.text.strip()
        user_states[user_id]["text"] = text
        user_states[user_id]["step"] = "WAITING_FOR_DATETIME"
        await update.message.reply_text(
            "📅 **Час нагадування** (`18:30`, або з повторенням `щотижня у вівторок, четвер 15:00`):",
            parse_mode="Markdown",
        )
    elif state == "WAITING_FOR_DATETIME":
        dt_text = update.message.text.strip()
        remind_text = user_states[user_id].get("text", "Нагадування")
        full_text = f"{remind_text} {dt_text}"
        await parse_and_schedule_reminder(update, context, full_text)


def parse_weekdays(text: str):
    found_days = []
    lower_text = text.lower()
    for word, day_idx in WEEKDAYS_MAP.items():
        if word in lower_text:
            if day_idx not in found_days:
                found_days.append(day_idx)
    return found_days


async def parse_and_schedule_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, full_text: str):
    user_id = update.effective_user.id
    now = datetime.datetime.now()

    repeat = "none"
    target_weekdays = []

    if "щодня" in full_text.lower():
        repeat = "daily"
        full_text = re.sub(r"(?i)\s*щодня", "", full_text)
    elif "щотижня" in full_text.lower():
        repeat = "weekly"
        full_text = re.sub(r"(?i)\s*щотижня", "", full_text)
        target_weekdays = parse_weekdays(full_text)
        for word in WEEKDAYS_MAP.keys():
            full_text = re.sub(r"(?i)\b" + word + r"\b", "", full_text)
        full_text = re.sub(r"(?i)\b(у|в|по)\b", "", full_text)

    match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}|\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}|\d{1,2}:\d{2})$", full_text)

    if not match:
        await update.message.reply_text(
            "❌ **Формат часу не розпізнано.** Спробуйте: `/remind Назва 18:30` або `/remind Назва щотижня у понеділок 15:00`",
            parse_mode="Markdown",
        )
        return

    dt_str = match.group(1)
    reminder_title = full_text[:match.start()].strip() or "Нагадування"
    reminder_title = re.sub(r"[\s,]+$", "", reminder_title)

    target_dt = None
    try:
        if re.match(r"^\d{1,2}:\d{2}$", dt_str):
            h, m = map(int, dt_str.split(":"))
            target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            
            if repeat == "weekly" and target_weekdays:
                days_ahead = [(d - now.weekday()) % 7 for d in target_weekdays]
                min_days = min(days_ahead)
                if min_days == 0 and target_dt <= now:
                    future_days = [d for d in days_ahead if d > 0]
                    min_days = min(future_days) if future_days else 7
                target_dt += datetime.timedelta(days=min_days)
            else:
                if target_dt <= now:
                    target_dt += datetime.timedelta(days=1)

        elif re.match(r"^\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}$", dt_str):
            day_month, time_part = dt_str.split()
            d, m = map(int, day_month.split("."))
            h, min_p = map(int, time_part.split(":"))
            target_dt = datetime.datetime(now.year, m, d, h, min_p)
            if target_dt <= now:
                target_dt = datetime.datetime(now.year + 1, m, d, h, min_p)
        elif re.match(r"^\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}$", dt_str):
            date_part, time_part = dt_str.split()
            d, m, y = map(int, date_part.split("."))
            h, min_p = map(int, time_part.split(":"))
            target_dt = datetime.datetime(y, m, d, h, min_p)
    except Exception:
        target_dt = None

    if not target_dt or target_dt <= now:
        await update.message.reply_text("❌ Вказано некоректну дату.")
        return

    delay = (target_dt - now).total_seconds()
    
    rem_id = str(int(datetime.datetime.now().timestamp()))
    job = context.job_queue.run_once(
        send_reminder,
        when=delay,
        user_id=user_id,
        data={
            "title": reminder_title, 
            "repeat": repeat, 
            "weekdays": target_weekdays, 
            "id": rem_id,
            "time_str": dt_str
        },
    )

    if user_id not in user_reminders:
        user_reminders[user_id] = {}

    user_reminders[user_id][rem_id] = {
        "title": reminder_title,
        "time": target_dt,
        "repeat": repeat,
        "weekdays": target_weekdays,
        "time_str": dt_str,
        "job_name": job.name,
    }

    user_states.pop(user_id, None)

    repeat_desc = ""
    if repeat == "daily":
        repeat_desc = " 🔁 щодня"
    elif repeat == "weekly":
        if target_weekdays:
            days_names = [list(WEEKDAYS_MAP.keys())[list(WEEKDAYS_MAP.values()).index(d)] for d in sorted(target_weekdays)]
            repeat_desc = f" 🔁 щотижня ({', '.join(days_names)})"
        else:
            repeat_desc = " 🔁 щотижня"

    formatted_time = target_dt.strftime("%d.%m.%Y о %H:%M")
    await update.message.reply_text(
        f"⏰ **Нагадування встановлено!**\n\n📌 *{reminder_title}*\n📅 {formatted_time}{repeat_desc}",
        parse_mode="Markdown",
    )


# --- КЕРУВАННЯ НАГАДУВАННЯМИ ---

async def my_reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reminders = user_reminders.get(user_id, {})

    if not reminders:
        await update.message.reply_text("📭 Активних нагадувань немає.")
        return

    keyboard = []
    for rem_id, data in reminders.items():
        time_str = data["time"].strftime("%d.%m %H:%M")
        rep_icon = " 🔁" if data["repeat"] != "none" else ""
        btn_text = f"⏰ {data['title']} — {time_str}{rep_icon}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"editrem_{rem_id}")])

    await update.message.reply_text(
        "📋 **Ваші нагадування:**",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.user_id
    title = job.data.get("title", "Нагадування")
    repeat = job.data.get("repeat", "none")
    weekdays = job.data.get("weekdays", [])
    rem_id = job.data.get("id")
    time_str = job.data.get("time_str", "12:00")

    await context.bot.send_message(
        chat_id=user_id,
        text=f"🔔 **НАГАДУВАННЯ**\n\n{title}",
        parse_mode="Markdown",
    )

    now = datetime.datetime.now()
    next_time = None

    if repeat == "daily":
        next_time = now + datetime.timedelta(days=1)
    elif repeat == "weekly":
        if weekdays:
            h, m = map(int, time_str.split(":"))
            current_day = now.weekday()
            
            days_ahead = []
            for d in weekdays:
                diff = (d - current_day) % 7
                if diff == 0:
                    diff = 7
                days_ahead.append(diff)
            
            min_diff = min(days_ahead)
            next_time = now.replace(hour=h, minute=m, second=0, microsecond=0) + datetime.timedelta(days=min_diff)
        else:
            next_time = now + datetime.timedelta(weeks=1)
    elif repeat == "monthly":
        next_time = now + datetime.timedelta(days=30)

    if next_time:
        new_job = context.job_queue.run_once(
            send_reminder,
            when=next_time - now,
            user_id=user_id,
            data={"title": title, "repeat": repeat, "weekdays": weekdays, "id": rem_id, "time_str": time_str},
        )
        if user_id in user_reminders and rem_id in user_reminders[user_id]:
            user_reminders[user_id][rem_id]["time"] = next_time
            user_reminders[user_id][rem_id]["job_name"] = new_job.name
    else:
        if user_id in user_reminders:
            user_reminders[user_id].pop(rem_id, None)


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("editrem_"):
        rem_id = data.split("_")[1]
        remData = user_reminders.get(user_id, {}).get(rem_id)

        if not remData:
            await query.edit_message_text("❌ Нагадування не знайдено.")
            return

        keyboard = [
            [InlineKeyboardButton("🗑 Видалити", callback_data=f"delrem_{rem_id}")],
            [InlineKeyboardButton("🔄 Змінити", callback_data=f"recreatorem_{rem_id}")],
        ]
        time_str = remData["time"].strftime("%d.%m.%Y %H:%M")
        await query.edit_message_text(
            f"⚙️ **Керування:**\n\n📌 *{remData['title']}*\n📅 {time_str}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("delrem_"):
        rem_id = data.split("_")[1]
        remData = user_reminders.get(user_id, {}).pop(rem_id, None)

        if remData:
            current_jobs = context.job_queue.get_jobs_by_name(remData["job_name"])
            for job in current_jobs:
                job.schedule_removal()
            await query.edit_message_text("🗑 **Видалено.**")

    elif data.startswith("recreatorem_"):
        rem_id = data.split("_")[1]
        remData = user_reminders.get(user_id, {}).pop(rem_id, None)

        if remData:
            current_jobs = context.job_queue.get_jobs_by_name(remData["job_name"])
            for job in current_jobs:
                job.schedule_removal()

            user_states[user_id] = {"step": "WAITING_FOR_TEXT"}
            await query.edit_message_text(
                "📝 **Зміна нагадування**\n\nВведіть новий текст:",
                parse_mode="Markdown",
            )


def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN", "8765392289:AAEmBrLRy_QqKdfYYj0509VVms1MoH2ud6k")
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("remind", remind_command))
    application.add_handler(CommandHandler("myreminders", my_reminders_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(CallbackQueryHandler(handle_buttons))

    application.run_polling()


if __name__ == "__main__":
    main()
