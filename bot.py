# bot.py
import uuid
import os
import io
from PIL import Image
import pytesseract
import telebot
from telebot import types

# --- CONFIG ---
BOT_TOKEN = "7465576071:AAFTDiAkU4hIsfY4SHrV9WLEzP4cBfz4wQ0"      # <<-- Put the new token here locally
ADMIN_CHAT_ID = 5468738122               # <<-- your Telegram numeric id (no quotes)

# Payment details (show to users)
UPI_VPA = "carrerhelp@ybl"
UPI_INSTRUCTIONS = (
    "⚠️ Important: When you complete UPI payment, *add the order ID in the UPI 'Note' / 'Message' field*. "
    "Example: ORDER-AB12\n\n"
    "Then send the payment screenshot in this chat. The bot will try to auto-verify the screenshot."
)

# Docs (view-only links or file_ids)
DOCS = {
    "student": [
        ("📄 Resume Templates", "https://drive.google.com/file/d/ABC123/view?usp=sharing"),
        ("👥 HR Contacts", "https://drive.google.com/file/d/DEF456/view?usp=sharing"),
    ],
    "pro": [
        ("📄 Resume Templates", "https://drive.google.com/file/d/ABC123/view?usp=sharing"),
        ("👥 HR Contacts", "https://drive.google.com/file/d/GHI789/view?usp=sharing"),
        ("🔥 Hiring Now – Oct 2025", "https://drive.google.com/file/d/JKL012/view?usp=sharing"),
    ]
}

bot = telebot.TeleBot(BOT_TOKEN)

# --- In-memory stores (persist to DB if you scale) ---
pending_orders = {}   # order_id -> {user_id, plan, amount}
user_selection = {}   # user_id -> plan

# --- UTILITIES ---
def new_order_id():
    # short readable order id
    return "ORDER-" + uuid.uuid4().hex[:8].upper()

def send_docs(user_id, plan):
    try:
        bot.send_message(
            user_id,
            "🎉 *Access granted!* Here are your exclusive docs:\n\n⚠️ *Forwarding discouraged.*",
            parse_mode="Markdown",
            protect_content=True
        )
        for name, link in DOCS[plan]:
            # send as document using the link; Telegram will fetch by URL
            bot.send_message(user_id, f"{name}\n{link}")
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"Error sending docs to {user_id}: {e}")

# --- COMMANDS ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("1️⃣ Student Pack – ₹9")
    markup.add("2️⃣ Pro Pack – ₹19")
    markup.add("3️⃣ College Bulk – Contact")
    bot.reply_to(
        message,
        "📚 *HireFlow – Placement Intel*\n\nChoose a plan:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text and "Pack" in m.text)
def handle_selection(message):
    text = message.text
    if "Student" in text:
        plan = "student"
        amount = 9
    elif "Pro" in text:
        plan = "pro"
        amount = 19
    else:
        bot.reply_to(message, "📧 For bulk access, email: hireflow.in@gmail.com")
        return

    user_selection[message.chat.id] = plan

    # create order and store
    order_id = new_order_id()
    pending_orders[order_id] = {"user_id": message.chat.id, "plan": plan, "amount": amount}

    reply = (
        f"✅ *{text}*\n\n"
        f"Pay ₹{amount} via UPI:\n"
        f"📱 *UPI VPA*: `{UPI_VPA}`\n\n"
        f"{UPI_INSTRUCTIONS}\n"
        f"🔖 *Your Order ID*: `{order_id}`\n\n"
        "After payment, send the payment screenshot in this chat."
    )
    bot.send_message(message.chat.id, reply, parse_mode="Markdown")

    # alert admin
    bot.send_message(ADMIN_CHAT_ID, f"🆕 New order created:\nUser: {message.chat.id}\nPlan: {plan}\nOrder ID: {order_id}")

# --- PAYMENT SCREENSHOT HANDLING ---
@bot.message_handler(content_types=['photo'])
def handle_payment_photo(message):
    user_id = message.chat.id

    # find the order for this user (take the latest pending for that user)
    orders = [(oid, o) for oid,o in pending_orders.items() if o["user_id"] == user_id]
    if not orders:
        bot.reply_to(message, "❌ No pending order found. Please select a pack with /start first.")
        return

    # choose the most recent order for this user
    orders_sorted = sorted(orders, key=lambda x: x[1].get("amount",0), reverse=True)
    order_id, order_info = orders_sorted[-1] if orders_sorted else orders[0]

    bot.reply_to(message, "📸 Screenshot received. Attempting automatic verification...")

    # download photo file
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    image = Image.open(io.BytesIO(downloaded))

    # Try OCR
    try:
        text = pytesseract.image_to_string(image)
        text_upper = text.upper()
    except Exception as e:
        text_upper = ""
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ OCR error for order {order_id}: {e}")

    # Check if order_id present in OCR text
    if order_id in text_upper:
        # auto-approve
        send_docs(user_id, order_info["plan"])
        del pending_orders[order_id]
        bot.send_message(user_id, f"✅ Payment verified automatically for `{order_id}`. Enjoy your pack!", parse_mode="Markdown")
        bot.send_message(ADMIN_CHAT_ID, f"✅ Auto-approved order {order_id} for user {user_id}")
        return
    else:
        # Forward screenshot + info to admin for manual review
        caption = f"📌 Manual review needed\nOrder: {order_id}\nFrom user: {user_id}\nPlan: {order_info['plan']}\n\nUse /approve {user_id} to approve."
        forwarded = bot.send_photo(ADMIN_CHAT_ID, message.photo[-1].file_id, caption=caption)
        bot.send_message(user_id, "⚠️ We couldn't auto-verify your screenshot. Admin will review and approve shortly. If automatic verification fails, make sure your UPI note contains the exact order ID.")
        return

# --- ADMIN APPROVE / REJECT ---
@bot.message_handler(commands=['approve'])
def approve_user(message):
    if message.chat.id != ADMIN_CHAT_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.send_message(ADMIN_CHAT_ID, "Usage: /approve <user_id>")
        return
    try:
        user_id = int(parts[1])
        # find pending order for user
        pending = [(oid, o) for oid,o in pending_orders.items() if o["user_id"] == user_id]
        if not pending:
            bot.send_message(ADMIN_CHAT_ID, f"No pending order for user {user_id}")
            return
        # pick latest
        oid, oinfo = pending[-1]
        send_docs(user_id, oinfo["plan"])
        del pending_orders[oid]
        bot.send_message(ADMIN_CHAT_ID, f"✅ Approved {oid} -> {user_id}")
        bot.send_message(user_id, "✅ Payment verified and access granted by admin.")
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"Error in /approve: {e}")

@bot.message_handler(commands=['reject'])
def reject_user(message):
    if message.chat.id != ADMIN_CHAT_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.send_message(ADMIN_CHAT_ID, "Usage: /reject <user_id>")
        return
    try:
        user_id = int(parts[1])
        # remove pending orders for this user
        removed = [oid for oid,o in list(pending_orders.items()) if o["user_id"] == user_id]
        for oid in removed:
            del pending_orders[oid]
        bot.send_message(ADMIN_CHAT_ID, f"❌ Removed pending orders for {user_id}")
        bot.send_message(user_id, "❌ Your payment could not be verified. Please try again and include the order ID in your UPI note.")
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"Error in /reject: {e}")

# --- FALLBACK / HELP ---
@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.reply_to(message, "Use /start to choose a pack or send your payment screenshot after you pay.")

# --- RUN ---
if __name__ == "__main__":
    print("✅ Bot running...")
    bot.infinity_polling()
