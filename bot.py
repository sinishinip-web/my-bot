import os, re, sqlite3, asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from docx import Document

API_TOKEN = 'ВАШ_ТОКЕН_БОТА'
RATE_BR, RATE_RUB, RATE_EUR = 3.0, 87.0, 1.1
DB_FILE = "expenses.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, date_text TEXT, raw_text TEXT, amount_br REAL DEFAULT 0, amount_rub REAL DEFAULT 0, amount_usd REAL DEFAULT 0, amount_eur REAL DEFAULT 0, category_id INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
init_db()

CATEGORIES = {1: "1. Квартира", 2: "2. Продукты", 3: "3. Автомобиль", 4: "4. Разное", 5: "5. Практика", 6: "6. Жена", 7: "7. Дети", 8: "8. Развлечения", 9: "9. Прочее"}
GROUPS = {1: "А. Семейные", 2: "А. Семейные", 3: "А. Семейные", 4: "А. Семейные", 5: "Б. Личные", 6: "Б. Личные", 7: "Б. Личные", 8: "Б. Личные", 9: "Б. Личные"}
KEYWORDS = {
    1: ["аренда", "коммуналка", "уборка", "фильтр"],
    2: ["продукты", "рынок", "томям", "вино", "водка", "чай", "минералка", "котенка", "фрукты", "овощи", "дыня", "малина", "сливы", "грибы", "корм"],
    3: ["авто", "ремонт", "заправка", "бензин"],
    5: ["кабинет", "налог", "супервизор", "profdohod"],
    6: ["zhena", "cvety"],
    7: ["jarik", "alimenty", "detjam", "hot-dog", "picca", "agata"],
    8: ["chajnaja", "chaepitie", "naushniki"]
}

bot, dp = Bot(token=API_TOKEN), Dispatcher()

def check_hosting_reminder():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'last_reminder'")
    row = c.fetchone()
    now, need_remind = datetime.now(), False
    if row is None:
        c.execute("INSERT INTO settings (key, value) VALUES ('last_reminder', ?)", (now.strftime("%Y-%m-%d"),))
        conn.commit()
    else:
        if now - datetime.strptime(row[0], "%Y-%m-%d") >= timedelta(days=60):
            need_remind = True
            c.execute("UPDATE settings SET value = ? WHERE key = 'last_reminder'", (now.strftime("%Y-%m-%d"),))
            conn.commit()
    conn.close()
    return need_remind

def parse_amounts(text):
    matches = re.findall(r'(\d+(?:[.,]\d+)?)\s*(бр|р|₽|рр|\$|€)?', text.lower())
    br, rub, usd, eur = 0.0, 0.0, 0.0, 0.0
    if not matches:
        digits = re.findall(r'\b\d+(?:[.,]\d+)?\b', text)
        return sum(float(d.replace(',', '.')) for d in digits), rub, usd, eur
    for val_str, curr in matches:
        val_num = float(val_str.replace(',', '.'))
        if curr in ['', 'р', 'бр']: br += val_num
        elif curr in ['₽', 'рр']: rub += val_num
        elif curr == '$': usd += val_num
        elif curr == '€': eur += val_num
    return br, rub, usd, eur

def guess_category(text):
    t = text.lower()
    for cat_id, words in KEYWORDS.items():
        if any(w in t for w in words): return cat_id
    return None

def get_kb(tx_id):
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🏡 --- СЕМЕЙНЫЕ ---", callback_data="noop"))
    b.row(types.InlineKeyboardButton(text="1. Квартира", callback_data=f"set_{tx_id}_1"), types.InlineKeyboardButton(text="2. Продукты", callback_data=f"set_{tx_id}_2"))
    b.row(types.InlineKeyboardButton(text="3. Автомобиль", callback_data=f"set_{tx_id}_3"), types.InlineKeyboardButton(text="4. Разное", callback_data=f"set_{tx_id}_4"))
    b.row(types.InlineKeyboardButton(text="👤 --- ЛИЧНЫЕ ---", callback_data="noop"))
    b.row(types.InlineKeyboardButton(text="5. Практика", callback_data=f"set_{tx_id}_5"), types.InlineKeyboardButton(text="6. Жена", callback_data=f"set_{tx_id}_6"))
    b.row(types.InlineKeyboardButton(text="7. Дети", callback_data=f"set_{tx_id}_7"), types.InlineKeyboardButton(text="8. Развлечения", callback_data=f"set_{tx_id}_8"))
    b.row(types.InlineKeyboardButton(text="9. Прочее", callback_data=f"set_{tx_id}_9"))
    return b.as_markup()

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer("👋 Привет! Пишите сюда свои расходы. Я буду распределять их по категориям, а если засомневаюсь — спрошу.\n\n📊 Отчет за месяц: /report")
@dp.message(Command("report"))
async def cmd_report(m: types.Message):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT date_text, raw_text, amount_br, amount_rub, amount_usd, amount_eur, category_id FROM transactions WHERE user_id = ?", (m.from_user.id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await m.answer("📭 У вас пока нет записанных расходов.")
        return
    await m.answer("🔄 Формирую отчеты...")
    data = {i: {"br": 0.0, "rub": 0.0, "usd": 0.0, "eur": 0.0, "logs": []} for i in CATEGORIES}
    for dt, raw, br, rub, usd, eur, cat_id in rows:
        if not cat_id or cat_id not in data: cat_id = 9
        data[cat_id]["br"] += br; data[cat_id]["rub"] += rub; data[cat_id]["usd"] += usd; data[cat_id]["eur"] += eur
        data[cat_id]["logs"].append(f"[{dt}]  {raw}")
    g_totals = {"А. Семейные": 0.0, "Б. Личные": 0.0}
    c_usd_totals = {}
    for c_id, c_data in data.items():
        c_usd = (c_data["br"] / RATE_BR) + (c_data["rub"] / RATE_RUB) + c_data["usd"] + (c_data["eur"] * RATE_EUR)
        c_usd_totals[c_id] = c_usd
        g_totals[GROUPS[c_id]] += c_usd
    grand = g_totals["А. Семейные"] + g_totals["Б. Личные"]
    m_name = datetime.now().strftime("%m.%Y")
    lines = [f"**Структура расходов за {m_name}:**\n"]
    for g in ["А. Семейные", "Б. Личные"]:
        lines.append(f"**{g}**: **{g_totals[g]:.2f}$**")
        for c_id in CATEGORIES:
            if GROUPS[c_id] == g:
                cd = data[c_id]
                orig = []
                if cd["br"] > 0: orig.append(f"{cd['br']:.1f()} бр".replace('.0 бр', ' бр'))
                if cd["rub"] > 0: orig.append(f"{cd['rub']:.1f()} ₽".replace('.0 ₽', ' ₽'))
                if cd["usd"] > 0: orig.append(f"{cd['usd']:.1f()}$".replace('.0$', '$'))
                if cd["eur"] > 0: orig.append(f"{cd['eur']:.1f()}€".replace('.0€', '€'))
                lines.append(f"**{CATEGORIES[c_id]}**\n--- Итого: {' | '.join(orig) if orig else '0 бр'} [Всего: **{c_usd_totals[c_id]:.2f}$**]")
        lines.append("")
    lines.append("==============================\n" + f"**ОБЩИЙ ИТОГ ЗА МЕСЯЦ (А + Б): {grand:.2f} $**\n" + "==============================")
    
    doc = Document()
    doc.add_heading(f"Структура расходов за {m_name}", level=0)
    for g in ["А. Семейные", "Б. Личные"]:
        doc.add_heading(f"{g}: {g_totals[g]:.2f}$", level=1)
        for c_id in CATEGORIES:
            if GROUPS[c_id] == g:
                doc.add_heading(CATEGORIES[c_id], level=2)
                cd = data[c_id]
                orig = []
                if cd["br"] > 0: orig.append(f"{cd['br']} бр")
                if cd["rub"] > 0: orig.append(f"{cd['rub']} ₽")
                if cd["usd"] > 0: orig.append(f"{cd['usd']}$")
                if cd["eur"] > 0: orig.append(f"{cd['eur']}€")
                p = doc.add_paragraph()
                p.add_run(f"--- Итого: {' | '.join(orig) if orig else '0 бр'} [Всего: {c_usd_totals[c_id]:.2f}$] ---").bold = True
                for log in cd["logs"]: doc.add_paragraph(log)
        doc.add_paragraph("\n")
    doc.add_paragraph("=============================================")
    p_f = doc.add_paragraph()
    p_f.add_run(f"ОБЩИЙ ИТОГ ЗА МЕСЯЦ (А + Б): {grand:.2f} $").bold = True
    doc.add_paragraph("=============================================")
    f_path = f"Отчет_{m_name}.docx"
    doc.save(f_path)
    await m.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    await m.answer_document(types.FSInputFile(f_path), caption="📎 Полный отчет.")
    if os.path.exists(f_path): os.remove(f_path)

@dp.message()
async def handle_text(m: types.Message):
    if not m.text or m.text.startswith('/'): return
    dt_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    br, rub, usd, eur = parse_amounts(m.text)
    if br == 0 and rub == 0 and usd == 0 and eur == 0:
        await m.answer("⚠️ Я не нашел сумму. Пример: `Рынок 45`")
        return
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("INSERT INTO transactions (user_id, date_text, raw_text, amount_br, amount_rub, amount_usd, amount_eur, category_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (m.from_user.id, dt_str, m.text, br, rub, usd, eur, None))
    tx_id = cursor.lastrowid; conn.commit(); conn.close()
    g_id = guess_category(m.text)
    if g_id:
        conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET category_id = ? WHERE id = ?", (g_id, tx_id)); conn.commit(); conn.close()
        kb = InlineKeyboardBuilder()
        kb.row(types.InlineKeyboardButton(text="✏️ Изменить категорию", callback_data=f"change_{tx_id}"))
        curs = []
        if br > 0: curs.append(f"{br} бр")
        if rub > 0: curs.append(f"{rub} ₽")
        if usd > 0: curs.append(f"{usd}$")
        if eur > 0: curs.append(f"{eur}€")
        await m.answer(f"✅ Записано в **\"{CATEGORIES[g_id]}\"** ({', '.join(curs)})", reply_markup=kb.as_markup(), parse_mode=ParseMode.MARKDOWN)
    else:
        await m.answer(f"❓ **Не могу определить категорию:**\n_\"{m.text}\"_\n\nВыберите раздел:", reply_markup=get_kb(tx_id), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query()
async def process_callback(cb: types.CallbackQuery):
    if cb.data == "noop": await cb.answer(); return
    if cb.data.startswith("set_"):
        _, tx_id, cat_id = cb.data.split('_')
        tx_id, cat_id = int(tx_id), int(cat_id)
        conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET category_id = ? WHERE id = ?", (cat_id, tx_id)); conn.commit(); conn.close()
        kb = InlineKeyboardBuilder(); kb.row(types.InlineKeyboardButton(text="✏️ Изменить категорию", callback_data=f"change_{tx_id}"))
        await cb.message.edit_text(f"✅ Успешно сохранено в: **{CATEGORIES[cat_id]}**", reply_markup=kb.as_markup(), parse_mode=ParseMode.MARKDOWN)
        await cb.answer("Сохранено!")
    elif cb.data.startswith("change_"):
        tx_id = int(cb.data.split('_')[1])
        await cb.message.edit_text("🔄 Выберите новую категорию:", reply_markup=get_kb(tx_id))
        await cb.answer()

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
