import logging
import re
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ------------------- CONFIGURAÇÃO -------------------

TELEGRAM_TOKEN = "8026430612:AAFEXEEghOQ6_uynFULoHjDoUNfLN6Ac8vY"
SHEET_ID        = "1bFUEJJPyUt3ORFzp_UsigNo92d7tXkyaN9oJNkEXHLs"
WORKSHEET_NAME  = "Preços"

# Autenticação Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
CREDS  = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
GC     = gspread.authorize(CREDS)

# ------------------- LOGGER -------------------

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------- FUNÇÕES SHEETS -------------------

def get_mapa_precos() -> dict[str, str]:
    """
    Carrega tickers e preços da aba WORKSHEET_NAME:
    Coluna A = ticker, Coluna B = GOOGLEFINANCE(...)
    Retorna dicionário { 'PETR4.SA': 'R$ 30,45', ... }
    """
    sh = GC.open_by_key(SHEET_ID)
    ws = sh.worksheet(WORKSHEET_NAME)
    tickers = ws.col_values(1)[1:]   # pula cabeçalho
    precos  = ws.col_values(2)[1:]
    return {t.strip().upper(): p for t, p in zip(tickers, precos)}

def get_preco_sheet(ticker: str) -> float | None:
    """
    Busca preço no dicionário re-carregado, limpa R$ e retorna float.
    """
    mapa = get_mapa_precos()
    raw = mapa.get(ticker)
    if not raw:
        return None
    cleaned = re.sub(r"[^\d,\.]", "", raw)
    try:
        return float(cleaned.replace(",", "."))
    except ValueError:
        return None

# ------------------- ARMAZENA ALERTAS -------------------

# { chat_id: [ (ticker, alvo_float), ... ] }
alertas: dict[int, list[tuple[str, float]]] = {}

# ------------------- HANDLERS -------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "🤖 *Bot de Ativos* pronto!\n\n"
        "/preco `<TICKER>` — retorna preço da planilha.\n"
        "/alerta `<TICKER>` `<PREÇO>` — cria alerta.\n"
        "/alertas — lista seus alertas.\n"
        "/remover `<TICKER>` `<PREÇO>` — remove alerta.\n"
        "/mapa  — exibe o 50 primeiros aitvos da lista\n"
    )
    await update.message.reply_markdown(texto)

async def preco(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return await update.message.reply_text("Uso: /preco TICKER")
    t = context.args[0].strip().upper()
    if not t.endswith(".SA"):
        t += ".SA"
    p = get_preco_sheet(t)
    if p is None:
        await update.message.reply_markdown(f"❌ Ticker *{t}* não encontrado ou sem dado.")
    else:
        await update.message.reply_markdown(f"💰 *{t}*: R$ {p:.2f}")

async def alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        return await update.message.reply_text("Uso: /alerta TICKER PREÇO_ALVO")
    chat_id = update.effective_chat.id
    t = context.args[0].strip().upper()
    if not t.endswith(".SA"):
        t += ".SA"
    try:
        alvo = float(context.args[1].replace(",", "."))
    except ValueError:
        return await update.message.reply_text("❌ Preço alvo inválido.")
    alertas.setdefault(chat_id, []).append((t, alvo))
    await update.message.reply_markdown(f"🔔 Alerta criado: *{t}* <= R$ {alvo:.2f}")

async def listar_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    lst = alertas.get(chat_id, [])
    if not lst:
        return await update.message.reply_text("Você não tem alertas ativos.")
    texto = "📋 *Seus alertas:*\n" + "\n".join(f"- {t} <= R$ {a:.2f}" for t, a in lst)
    await update.message.reply_markdown(texto)

async def remover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        return await update.message.reply_text("Uso: /remover TICKER PREÇO_ALVO")
    chat_id = update.effective_chat.id
    t = context.args[0].strip().upper()
    if not t.endswith(".SA"):
        t += ".SA"
    try:
        alvo = float(context.args[1].replace(",", "."))
    except ValueError:
        return await update.message.reply_text("❌ Preço alvo inválido.")
    lst = alertas.get(chat_id, [])
    alertas[chat_id] = [x for x in lst if not (x[0] == t and abs(x[1] - alvo) < 1e-6)]
    await update.message.reply_markdown(f"🗑️ Alerta removido: *{t}* <= R$ {alvo:.2f}")

# ------------------- CHECAGEM PERIÓDICA -------------------

async def checar_alertas(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    for chat_id, lst in list(alertas.items()):
        for t, alvo in lst.copy():
            p = get_preco_sheet(t)
            if p is None:
                continue
            if p <= alvo:
                msg = f"🚨 *Alerta!* {t} atingiu R$ {p:.2f} (<= {alvo:.2f})"
                await bot.send_message(chat_id, msg, parse_mode="Markdown")
                alertas[chat_id].remove((t, alvo))


async def mapa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando de debug: mostra os 50 primeiros tickers carregados do Sheets.
    """
    mapa = get_mapa_precos()
    # lista até 50 tickers
    lista = list(mapa.keys())[:50]
    txt = "🔍 *Tickers carregados*: \n" + "\n".join(lista)
    await update.message.reply_markdown(txt)


# ------------------- MAIN -------------------

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("preco", preco))
    app.add_handler(CommandHandler("alerta", alerta))
    app.add_handler(CommandHandler("alertas", listar_alertas))
    app.add_handler(CommandHandler("remover", remover))
    app.add_handler(CommandHandler("mapa", mapa))


    # agenda checagem a cada 60s
    app.job_queue.run_repeating(checar_alertas, interval=60, first=10)

    logger.info("🤖 Bot rodando...")
    app.run_polling()

if __name__ == "__main__":
    main()
