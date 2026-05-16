import logging
import os
import sqlite3
import sys
from datetime import datetime
from fpdf import FPDF
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    ConversationHandler, 
    ContextTypes
)
from telegram.request import HTTPXRequest

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Conversation States for Billing (0 to 13)
CHOOSING_TYPE, BANK_DETAILS, SHOW_CUST_GST, CUST_NAME, CUST_PHONE, CUST_GSTIN, CUST_ADDR, \
ITEM_NAME, ITEM_HSN, ITEM_QTY, ITEM_UNIT, ITEM_RATE, ITEM_GST, ADDING_MORE = range(14)

# Conversation States for Bank Editing (14 to 17)
EDIT_BANK_NAME, EDIT_ACC_HOLDER, EDIT_ACC_NO, EDIT_IFSC = range(14, 18)

# Fixed Seller Data
SELLER_NAME = "KRIDHA ESSENTIALS"
SELLER_ADDR = "B 1330 nag mandir road shastri nagar new delhi 110052"
SELLER_PHONE = "7065231699"
SELLER_STATE = "07-Delhi"
SELLER_GSTIN = "07DJWPG1456G1ZX"

def init_db():
    conn = sqlite3.connect('billing_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no INTEGER,
            date TEXT,
            customer_name TEXT,
            amount REAL,
            bill_type TEXT,
            file_id TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bank_config (
            id INTEGER PRIMARY KEY,
            bank_name TEXT,
            holder_name TEXT,
            account_no TEXT,
            ifsc_code TEXT
        )
    ''')
    cursor.execute('SELECT COUNT(*) FROM bank_config')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO bank_config (id, bank_name, holder_name, account_no, ifsc_code)
            VALUES (1, 'Kotak Mahindra Bank', 'Princi Gupta', '738293984884', 'KKBK0037388')
        ''')
    conn.commit()
    conn.close()

init_db()

def get_next_invoice_no():
    conn = sqlite3.connect('billing_history.db')
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(invoice_no) FROM history')
    val = cursor.fetchone()[0]
    conn.close()
    return (val + 1) if val is not None else 1

def get_bank_details():
    conn = sqlite3.connect('billing_history.db')
    cursor = conn.cursor()
    cursor.execute('SELECT bank_name, holder_name, account_no, ifsc_code FROM bank_config WHERE id = 1')
    row = cursor.fetchone()
    conn.close()
    return row

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, getattr(self, 'invoice_header', 'TAX INVOICE'), 0, 1, 'C')
        self.line(10, 20, 200, 20)
        self.ln(5)

# ==================== BILLING CONVERSATION FLOW ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['items'] = []
    
    reply_keyboard = [['GST Invoice', 'Estimate Bill']]
    await update.message.reply_text(
        "🧾 Kridha Essentials Billing Bot mein swagat hai!\nKaisa bill banana hai?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return CHOOSING_TYPE

async def bill_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['type'] = update.message.text
    reply_keyboard = [['Yes', 'No']]
    await update.message.reply_text("🏦 Bank details show karni hain?", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
    return BANK_DETAILS

async def bank_details_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['show_bank'] = update.message.text
    if context.user_data['type'] == 'GST Invoice':
        reply_keyboard = [['Yes', 'No']]
        await update.message.reply_text("🆔 Customer ka GSTIN show karna hai?", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
        return SHOW_CUST_GST
    else:
        context.user_data['show_cust_gst'] = 'No'
        context.user_data['c_gstin'] = "N/A"
        await update.message.reply_text("👤 Customer Name:", reply_markup=ReplyKeyboardRemove())
        return CUST_NAME

async def show_cust_gst_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['show_cust_gst'] = update.message.text
    await update.message.reply_text("👤 Customer Name:", reply_markup=ReplyKeyboardRemove())
    return CUST_NAME

async def cust_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_name'] = update.message.text
    await update.message.reply_text("📞 Customer Contact/Phone:")
    return CUST_PHONE

async def cust_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_phone'] = update.message.text
    if context.user_data['type'] == 'GST Invoice' and context.user_data['show_cust_gst'] == 'Yes':
        await update.message.reply_text("📝 Customer GSTIN:")
        return CUST_GSTIN
    context.user_data['c_gstin'] = "N/A"
    await update.message.reply_text("🏠 Customer Address:")
    return CUST_ADDR

async def cust_gstin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_gstin'] = update.message.text
    await update.message.reply_text("🏠 Customer Address:")
    return CUST_ADDR

async def cust_addr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_addr'] = update.message.text
    await update.message.reply_text("📦 Chaliye Items add karte hain.\nItem Description / Name:")
    return ITEM_NAME

async def item_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_item'] = {'name': update.message.text}
    await update.message.reply_text(f"🔢 '{update.message.text}' ka HSN Code (Agar nahi hai to '-' likhein):")
    return ITEM_HSN

async def item_hsn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_item']['hsn'] = update.message.text
    await update.message.reply_text("⚖️ Quantity:")
    return ITEM_QTY

async def item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['current_item']['qty'] = float(update.message.text)
        reply_keyboard = [['Pcs', 'Mtr', 'Set']]
        await update.message.reply_text("📐 Unit select karein:", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
        return ITEM_UNIT
    except ValueError:
        await update.message.reply_text("❌ Kripya sahi number dalein. Quantity:")
        return ITEM_QTY

async def item_unit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_item']['unit'] = update.message.text
    await update.message.reply_text("💰 Price / Rate (Per Unit):", reply_markup=ReplyKeyboardRemove())
    return ITEM_RATE

async def item_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['current_item']['rate'] = float(update.message.text)
        if context.user_data['type'] == 'GST Invoice':
            await update.message.reply_text("📈 GST % (Kripya sirf number likhein jaise 5, 12, 18):")
            return ITEM_GST
        context.user_data['current_item']['gst'] = 0.0
        return await save_item(update, context)
    except ValueError:
        await update.message.reply_text("❌ Kripya sahi price dalein. Price:")
        return ITEM_RATE

async def item_gst(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['current_item']['gst'] = float(update.message.text)
        return await save_item(update, context)
    except ValueError:
        await update.message.reply_text("❌ Kripya sahi GST % dalein. GST %:")
        return ITEM_GST

async def save_item(update, context):
    context.user_data['items'].append(context.user_data['current_item'])
    reply_keyboard = [['+ Add Another Item', 'Generate Final Bill']]
    await update.message.reply_text(
        "✅ Item successfully add ho gaya! Agla step select karein:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ADDING_MORE

async def generate_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Generating PDF, please wait...", reply_markup=ReplyKeyboardRemove())
    user = context.user_data
    invoice_no = get_next_invoice_no()
    current_date = datetime.now().strftime('%d-%m-%Y')
    
    pdf = PDF()
    pdf.invoice_header = "TAX INVOICE" if user['type'] == 'GST Invoice' else "ESTIMATE / BILL"
    pdf.add_page()
    
    # Header Branding
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(110, 6, SELLER_NAME, 0, 0, 'L')
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(80, 6, f"GSTIN: {SELLER_GSTIN}", 0, 1, 'R')
    
    pdf.set_font("Arial", '', 9)
    seller_info = f"{SELLER_ADDR}\nPhone: {SELLER_PHONE}\nState: {SELLER_STATE}"
    pdf.multi_cell(110, 4, seller_info)
    pdf.ln(5)
    
    x_grid, y_grid = pdf.get_x(), pdf.get_y()
    
    # --- FIXED 3-COLUMN GRID BOXES (NO OVERLAPPING) ---
    # Column 1: Bill To (Width 65)
    pdf.rect(x_grid, y_grid, 65, 32)
    pdf.set_xy(x_grid+2, y_grid+2)
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(61, 4, "Bill To:", 0, 1)
    pdf.set_font("Arial", '', 8.5)
    pdf.cell(61, 4.5, f"Name: {user['c_name']}", 0, 1)
    pdf.cell(61, 4.5, f"Contact: {user['c_phone']}", 0, 1)
    pdf.set_xy(x_grid+2, pdf.get_y())
    pdf.multi_cell(61, 4, f"Address: {user['c_addr']}")
    
    # Column 2: Invoice Details (Width 65)
    pdf.set_xy(x_grid+65, y_grid)
    pdf.rect(x_grid+65, y_grid, 65, 32)
    pdf.set_xy(x_grid+67, y_grid+2)
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(61, 4, "Invoice Details:", 0, 1)
    pdf.set_font("Arial", '', 8.5)
    pdf.cell(61, 4.5, f"Invoice No: {invoice_no}", 0, 1)
    pdf.cell(61, 4.5, f"Date: {current_date}", 0, 1)
    
    # Column 3: Customer GSTIN (Width 60)
    pdf.set_xy(x_grid+130, y_grid)
    pdf.rect(x_grid+130, y_grid, 60, 32)
    pdf.set_xy(x_grid+132, y_grid+2)
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(56, 4, "Customer GSTIN:", 0, 1)
    pdf.set_font("Arial", '', 8.5)
    if user['type'] == 'GST Invoice' and user['show_cust_gst'] == 'Yes':
        pdf.cell(56, 4.5, user['c_gstin'], 0, 1)
    else:
        pdf.cell(56, 4.5, "N/A", 0, 1)
        
    pdf.set_xy(10, y_grid+37)

    # Main Items Table
    pdf.set_fill_color(242, 242, 242)
    pdf.set_font("Arial", 'B', 9)
    is_gst = (user['type'] == 'GST Invoice')
    
    pdf.cell(10, 7, "#", 1, 0, 'C', True)
    pdf.cell(65, 7, "Description", 1, 0, 'C', True)
    pdf.cell(20, 7, "HSN", 1, 0, 'C', True)
    pdf.cell(15, 7, "Qty", 1, 0, 'C', True)
    pdf.cell(15, 7, "Unit", 1, 0, 'C', True)
    pdf.cell(20, 7, "Price", 1, 0, 'C', True)
    if is_gst:
        pdf.cell(20, 7, "GST", 1, 0, 'C', True)
        pdf.cell(25, 7, "Total", 1, 1, 'C', True)
    else:
        pdf.cell(45, 7, "Total", 1, 1, 'C', True)

    pdf.set_font("Arial", '', 9)
    grand_total = 0.0
    sub_total = 0.0
    tax_rows = []
    for idx, itm in enumerate(user['items'], 1):
        base = itm['qty'] * itm['rate']
        tax = base * (itm['gst'] / 100.0) if is_gst else 0.0
        total = base + tax
        
        grand_total += total
        sub_total += base
        
        pdf.cell(10, 7, str(idx), 1, 0, 'C')
        pdf.cell(65, 7, itm['name'], 1, 0, 'L')
        pdf.cell(20, 7, itm['hsn'], 1, 0, 'C')
        pdf.cell(15, 7, str(itm['qty']), 1, 0, 'C')
        pdf.cell(15, 7, itm['unit'], 1, 0, 'C')
        pdf.cell(20, 7, f"{itm['rate']:.2f}", 1, 0, 'C')
        if is_gst:
            pdf.cell(20, 7, f"{tax:.2f}", 1, 0, 'C')
            pdf.cell(25, 7, f"{total:.2f}", 1, 1, 'C')
            if base > 0:
                tax_rows.append((itm['hsn'], base, tax/2.0, tax/2.0, tax))
        else:
            pdf.cell(45, 7, f"{total:.2f}", 1, 1, 'C')

    x_start, y_start = pdf.get_x(), pdf.get_y()
    
    if is_gst and len(tax_rows) > 0:
        pdf.set_font("Arial", 'B', 8)
        pdf.cell(25, 6, "HSN", 1, 0, 'C', True)
        pdf.cell(25, 6, "Taxable", 1, 0, 'C', True)
        pdf.cell(20, 6, "CGST", 1, 0, 'C', True)
        pdf.cell(20, 6, "SGST", 1, 0, 'C', True)
        pdf.cell(25, 6, "Total Tax", 1, 1, 'C', True)
        
        pdf.set_font("Arial", '', 8)
        for hsn, tx_base, cgst, sgst, tot_tx in tax_rows:
            pdf.cell(25, 6, hsn, 1, 0, 'C')
            pdf.cell(25, 6, f"{tx_base:.2f}", 1, 0, 'C')
            pdf.cell(20, 6, f"{cgst:.2f}", 1, 0, 'C')
            pdf.cell(20, 6, f"{sgst:.2f}", 1, 0, 'C')
            pdf.cell(25, 6, f"{tot_tx:.2f}", 1, 1, 'C')
            
        y_left_end = pdf.get_y()
        
        pdf.set_xy(x_start + 115, y_start)
        pdf.set_font("Arial", '', 9)
        pdf.cell(45, 6, "Taxable Total", 1, 0, 'L')
        pdf.cell(30, 6, f"{sub_total:.2f}", 1, 1, 'R')
        
        pdf.set_xy(x_start + 115, y_start + 6)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(45, 8, "Grand Total", 1, 0, 'L')
        pdf.cell(30, 8, f"{grand_total:.2f}", 1, 1, 'R')
        
        y_right_end = pdf.get_y()
        max_y = max(y_left_end, y_right_end)
    else:
        pdf.set_xy(x_start + 115, y_start)
        pdf.set_font("Arial", '', 9)
        pdf.cell(45, 6, "Sub Total", 1, 0, 'L')
        pdf.cell(30, 6, f"{sub_total:.2f}", 1, 1, 'R')
        
        pdf.set_xy(x_start + 115, y_start + 6)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(45, 8, "Grand Total", 1, 0, 'L')
        pdf.cell(30, 8, f"{grand_total:.2f}", 1, 1, 'R')
        max_y = pdf.get_y()

    pdf.set_xy(10, max_y + 3)
    pdf.set_font("Arial", 'I', 8)
    pdf.cell(190, 5, "E. & O.E.", 0, 1, 'R')
    pdf.ln(2)

    # Bank Details Block (Dynamic Data from DB)
    if user['show_bank'] == 'Yes':
        b_name, b_holder, b_acc, b_ifsc = get_bank_details()
        pdf.set_font("Arial", 'B', 9)
        current_y = pdf.get_y()
        pdf.rect(10, current_y, 190, 24)
        pdf.set_x(12)
        pdf.cell(0, 5, "Seller Bank Details:", 0, 1, 'L')
        pdf.set_font("Arial", '', 8.5)
        pdf.set_x(12)
        pdf.cell(0, 4, f"Bank Name: {b_name} | Account Holder: {b_holder}", 0, 1)
        pdf.set_x(12)
        pdf.cell(0, 4, f"Account Number: {b_acc} | IFSC Code: {b_ifsc}", 0, 1)
        pdf.set_x(12)
        pdf.cell(0, 4, "Account Type: Current Account", 0, 1)
        pdf.ln(5)

    pdf.ln(5)
    pdf.set_font("Arial", '', 10)
    pdf.cell(0, 5, f"For {SELLER_NAME}", 0, 1, 'R')
    pdf.ln(12)
    pdf.cell(0, 5, "Authorized Signatory", 0, 1, 'R')

    month_name = datetime.now().strftime('%B') 
    clean_name = user['c_name'].replace(' ', '_')
    fname = f"Bill_{clean_name}_{invoice_no}_({month_name}).pdf"
    pdf.output(fname)
    
    sent_doc = await update.message.reply_document(
        document=open(fname, 'rb'), 
        caption=f"✨ *Kridha Essentials* \n🧾 Invoice #{invoice_no} ({user['type']}) taiyar hai!"
    )
    
    telegram_file_id = sent_doc.document.file_id
    
    conn = sqlite3.connect('billing_history.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO history (invoice_no, date, customer_name, amount, bill_type, file_id) VALUES (?, ?, ?, ?, ?, ?)',
                   (invoice_no, current_date, user['c_name'], grand_total, user['type'], telegram_file_id))
    conn.commit()
    conn.close()
    
    os.remove(fname)
    return ConversationHandler.END

# ==================== BANK DETAILS EDIT FLOW ====================

async def edit_bank_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏦 Bank Details edit karne ki process shuru ho gayi hai.\n\nNaya **Bank Name** bataiye:")
    return EDIT_BANK_NAME

async def edit_bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_b_name'] = update.message.text
    await update.message.reply_text("👤 **Account Holder Name** bataiye:")
    return EDIT_ACC_HOLDER

async def edit_acc_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_b_holder'] = update.message.text
    await update.message.reply_text("🔢 **Account Number** bataiye:")
    return EDIT_ACC_NO

async def edit_acc_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_b_acc'] = update.message.text
    await update.message.reply_text("🔤 **IFSC Code** bataiye:")
    return EDIT_IFSC

async def edit_ifsc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ifsc = update.message.text
    b_name = context.user_data['temp_b_name']
    b_holder = context.user_data['temp_b_holder']
    b_acc = context.user_data['temp_b_acc']
    
    conn = sqlite3.connect('billing_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE bank_config 
        SET bank_name = ?, holder_name = ?, account_no = ?, ifsc_code = ?
        WHERE id = 1
    ''', (b_name, b_holder, b_acc, ifsc))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Bank details successfully update ho gaye hain! Ab naye bills mein yehi details print honge.")
    context.user_data.clear()
    return ConversationHandler.END

# ==================== OTHER COMMAND HANDLERS ====================

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('billing_history.db')
    cursor = conn.cursor()
    cursor.execute('SELECT invoice_no, date, customer_name, amount, bill_type FROM history ORDER BY id DESC')
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("📭 Abhi tak koi billing history record nahi hui hai.")
        return
        
    history_msg = "📊 *Kridha Essentials - Invoice History:*\n\n"
    for row in rows:
        history_msg += f"📅 *{row[1]}* (Inv #{row[0]}) - {row[2]}\n💰 Rs. {row[3]:.2f} ({row[4]})\n📥 Download: /get_{row[0]}\n"
        history_msg += "‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\n"
        if len(history_msg) > 3500:
            break
            
    await update.message.reply_text(history_msg, parse_mode="Markdown")

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text
    try:
        inv_no = int(command.split('_')[1])
        conn = sqlite3.connect('billing_history.db')
        cursor = conn.cursor()
        cursor.execute('SELECT file_id, customer_name, bill_type FROM history WHERE invoice_no = ?', (inv_no,))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            await update.message.reply_document(document=result[0], caption=f"🔄 *History Backup* \n🧾 {result[2]} for {result[1]} (Inv #{inv_no})")
        else:
            await update.message.reply_text("❌ File database mein nahi mili.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Sahi format use karein, e.g., /get_1")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Process cancel kar diya gaya.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    TOKEN = "8718587710:AAFrD0Utr2TwRbEeMaAnSKxELWbj-5lRuCI" 
    PROXY_URL = "http://proxy.server:3128"
    
    # PythonAnywhere Correct Configured HTTPX Proxy
    custom_request = HTTPXRequest(proxy_url=PROXY_URL, read_timeout=30, connect_timeout=30)
    
    app = (
        Application.builder()
        .token(TOKEN)
        .request(custom_request)
        .build()
    )

    billing_conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bill_type_choice)],
            BANK_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_details_choice)],
            SHOW_CUST_GST: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_cust_gst_choice)],
            CUST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cust_name)],
            CUST_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, cust_phone)],
            CUST_GSTIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, cust_gstin)],
            CUST_ADDR: [MessageHandler(filters.TEXT & ~filters.COMMAND, cust_addr)],
            ITEM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_name)],
            ITEM_HSN: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_hsn)],
            ITEM_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_qty)],
            ITEM_UNIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_unit)],
            ITEM_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_rate)],
            ITEM_GST: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_gst)],
            ADDING_MORE: [
                MessageHandler(filters.Regex('^\+ Add Another Item$'), item_name),
                MessageHandler(filters.Regex('^Generate Final Bill$'), generate_bill)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    bank_conv = ConversationHandler(
        entry_points=[CommandHandler('editbank', edit_bank_start)],
        states={
            EDIT_BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_name)],
            EDIT_ACC_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_acc_holder)],
            EDIT_ACC_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_acc_no)],
            EDIT_IFSC: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_ifsc)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(CommandHandler('history', show_history))
    app.add_handler(MessageHandler(filters.Regex('^/get_'), handle_download))
    app.add_handler(billing_conv)
    app.add_handler(bank_conv)
    
    print("Bot fixed for PythonAnywhere running cleanly...")
    app.run_polling()

if __name__ == '__main__':
    main()
