# -*- coding: utf-8 -*-
import http.server
import socketserver
import threading
import os
import asyncio
import psycopg2
import logging
import re
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

# --- 1. TRUCO PARA RENDER (SERVIDOR WEB DUMMY) ---
def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    handler = http.server.SimpleHTTPRequestHandler
    try:
        with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
            print(f"✅ Servidor dummy activo en puerto {port}")
            httpd.serve_forever()
    except Exception as e:
        print(f"Error en servidor dummy: {e}")

# Iniciamos el hilo para que Render no cierre la conexión
threading.Thread(target=start_dummy_server, daemon=True).start()

# --- 2. CONFIGURACIÓN Y LOGGING ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = "postgresql://solardb_qsmc_user:e4m42uewjIpJCPeA53UEiVNHzKvHOmq3@dpg-d74gr9vpm1nc738uc8vg-a.frankfurt-postgres.render.com/solardb_qsmc"
TOKEN_BOT = "8715828197:AAFOcTECqUo-EygBaKA8EMBc8ohkn-S5FbA"

# Estados de la conversación
MENU, VIVIENDA, PROBLEMA, CONSUMO, NOMBRE, BARRIO = range(6)
TELEFONO_POST, DIRECCION_POST = range(6, 8)

# --- 3. LÓGICA DE CALENDARIO ---
def obtener_proximos_dias_laborables(cantidad=5):
    dias = []
    fecha_actual = datetime.now()
    while len(dias) < cantidad:
        fecha_actual += timedelta(days=1)
        if fecha_actual.weekday() < 5: # Lunes a Viernes
            dias.append(fecha_actual)
    return dias

def obtener_horas_disponibles(fecha_str):
    todas_las_horas = [f"{h:02d}:00" for h in range(9, 18)]
    horas_ocupadas = []
    try:
        conexion = psycopg2.connect(DATABASE_URL)
        cursor = conexion.cursor()
        cursor.execute("SELECT visita_tecnica FROM clientes WHERE visita_tecnica LIKE %s", (f"{fecha_str}%",))
        resultados = cursor.fetchall()
        for (cita,) in resultados:
            if cita and " " in cita:
                horas_ocupadas.append(cita.split(" ")[1])
        conexion.close()
    except Exception as e:
        print(f"Error leyendo horarios: {e}")
    return [h for h in todas_las_horas if h not in horas_ocupadas]

# --- 4. FUNCIONES DEL BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    teclado = [['☀️ Ver Productos y Soluciones'], ['📊 Solicitar Estudio Gratuito']]
    await update.message.reply_text(
        "¡Hola! Bienvenido a *Solar Barrio* ☀️.\n\n¿En qué podemos asesorarte hoy?",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(teclado, one_time_keyboard=True, resize_keyboard=True)
    )
    return MENU

async def manejar_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    opcion = update.message.text
    if "Ver Productos" in opcion:
        await update.message.reply_text(
            "🟢 *Kit Ahorro*, 🔋 *Kit Anti-Apagones*, ⚡ *Kit Independencia*.\n\n¿Te gustaría un estudio personalizado?",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([['📊 Solicitar Estudio Gratuito']], resize_keyboard=True)
        )
        return MENU
    elif "Solicitar" in opcion:
        await update.message.reply_text("🏠 ¿Qué tipo de vivienda tienes?", 
            reply_markup=ReplyKeyboardMarkup([['Casa independiente', 'Adosado / Chalet'], ['Piso / Apartamento', 'Negocio / Local']], resize_keyboard=True))
        return VIVIENDA
    return await start(update, context)

async def recibir_vivienda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['vivienda'] = update.message.text
    await update.message.reply_text("⚡ ¿Cuál es tu problema principal?", 
        reply_markup=ReplyKeyboardMarkup([['Cortes de luz / Apagones', 'Facturas muy caras'], ['Ambas opciones']], resize_keyboard=True))
    return PROBLEMA

async def recibir_problema(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['problema'] = update.message.text
    await update.message.reply_text("💡 ¿Gasto mensual aproximado?", 
        reply_markup=ReplyKeyboardMarkup([['Menos de 50€', 'Entre 50€ y 100€'], ['Más de 100€', 'No lo sé seguro']], resize_keyboard=True))
    return CONSUMO

async def recibir_consumo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['consumo'] = update.message.text
    await update.message.reply_text("👤 Dime tu Nombre y Apellido:", reply_markup=ReplyKeyboardRemove())
    return NOMBRE

async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['nombre'] = update.message.text
    await update.message.reply_text(f"Un placer, {update.message.text}. 📍 ¿En qué Barrio o Ciudad estás?")
    return BARRIO

async def recibir_barrio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    datos = context.user_data
    datos['barrio'] = update.message.text
    chat_id = str(update.message.chat_id)
    usuario_tg = f"@{update.message.from_user.username}" if update.message.from_user.username else "Sin @"
    
    # Lógica de Kit
    if "Cortes" in datos['problema']:
        kit, precio, ahorro = "Kit Anti-Apagones", "5.490€", "85%"
    elif "Más de 100€" in datos['consumo']:
        kit, precio, ahorro = "Kit Ahorro Total Plus", "4.200€", "70%"
    else:
        kit, precio, ahorro = "Kit Ahorro Básico", "3.100€", "60%"

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""INSERT INTO clientes (fecha_contacto, usuario_tg, chat_id, tipo_vivienda, problema, consumo, nombre, barrio, telefono, estado_comercial, estado_obra, kit_asignado) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (datetime.now().strftime("%d/%m/%Y"), usuario_tg, chat_id, datos['vivienda'], datos['problema'], datos['consumo'], datos['nombre'], datos['barrio'], "Pendiente", "PRESUPUESTO ENVIADO", "PENDIENTE", kit))
        conn.commit()
        conn.close()
    except Exception as e: print(f"Error BD: {e}")

    teclado = [[InlineKeyboardButton("✅ Sí, visita gratuita", callback_data=f"venta_si_{chat_id}")],
               [InlineKeyboardButton("❌ No, gracias", callback_data=f"venta_no_{chat_id}")]]
    
    await update.message.reply_text(
        f"✅ *Estudio Listo*\n\nRecomendamos: *{kit}*\nPrecio: {precio}\nAhorro: {ahorro}\n\n¿Quieres una visita técnica gratuita?",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(teclado))
    return ConversationHandler.END

async def manejar_botones_venta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    respuesta, cid = query.data.split("_")[1], query.data.split("_")[2]
    
    if respuesta == "si":
        context.user_data['chat_id_cliente'] = cid
        await query.edit_message_text("✅ ¡Genial! Por favor, dime tu **número de teléfono**:", parse_mode="Markdown")
        return TELEFONO_POST
    else:
        await query.edit_message_text("❌ Entendido. ¡Gracias!")
        return ConversationHandler.END

async def recibir_telefono_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tel'] = update.message.text
    await update.message.reply_text("📍 Ahora dime tu **dirección completa**:", parse_mode="Markdown")
    return DIRECCION_POST

async def recibir_direccion_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dir_c = update.message.text
    cid = context.user_data['chat_id_cliente']
    tel = context.user_data['tel']
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE clientes SET telefono=%s, direccion=%s, estado_comercial='🔥 VISITA ACEPTADA' WHERE chat_id=%s", (tel, dir_c, cid))
        conn.commit()
        conn.close()
    except Exception as e: print(f"Error update: {e}")

    dias = obtener_proximos_dias_laborables(5)
    botones = [[InlineKeyboardButton(f"{d.strftime('%d/%m')}", callback_data=f"fecha_{d.strftime('%d/%m/%Y')}_{cid}")] for d in dias]
    await update.message.reply_text("🗓️ ¿Qué día te va mejor?", reply_markup=InlineKeyboardMarkup(botones))
    return ConversationHandler.END

async def manejar_seleccion_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    fecha, cid = query.data.split("_")[1], query.data.split("_")[2]
    horas = obtener_horas_disponibles(fecha)
    botones = [[InlineKeyboardButton(h, callback_data=f"hora_{fecha}_{h}_{cid}")] for h in horas]
    await query.edit_message_text(f"Selecciona hora para el {fecha}:", reply_markup=InlineKeyboardMarkup(botones))

async def manejar_seleccion_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    f, h, cid = query.data.split("_")[1], query.data.split("_")[2], query.data.split("_")[3]
    cita = f"{f} {h}"
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE clientes SET visita_tecnica=%s WHERE chat_id=%s", (cita, cid))
        conn.commit()
        conn.close()
    except Exception as e: print(e)
    await query.edit_message_text(f"✅ ¡Cita confirmada para el {cita}! ☀️")

# --- 5. MAIN ---
def main():
    app = Application.builder().token(TOKEN_BOT).build()
    
    conv_principal = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.Regex(re.compile(r'^(hola|buenas|quiero)', re.IGNORECASE)), start)],
        states={
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_menu)],
            VIVIENDA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_vivienda)],
            PROBLEMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_problema)],
            CONSUMO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_consumo)],
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre)],
            BARRIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_barrio)],
        }, fallbacks=[]
    )

    conv_post = ConversationHandler(
        entry_points=[CallbackQueryHandler(manejar_botones_venta, pattern="^venta_si")],
        states={
            TELEFONO_POST: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_telefono_post)],
            DIRECCION_POST: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_direccion_post)]
        }, fallbacks=[]
    )

    app.add_handler(conv_principal)
    app.add_handler(conv_post)
    app.add_handler(CallbackQueryHandler(manejar_seleccion_fecha, pattern="^fecha_"))
    app.add_handler(CallbackQueryHandler(manejar_seleccion_hora, pattern="^hora_"))
    app.add_handler(CallbackQueryHandler(manejar_botones_venta, pattern="^venta_no")) # Captura el NO

    print("☀️ Bot Solar Barrio ONLINE...")
    app.run_polling()

if __name__ == "__main__":
    main()
