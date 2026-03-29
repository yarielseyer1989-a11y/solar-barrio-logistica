# -*- coding: utf-8 -*-
import http.server
import socketserver
import threading
import os
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
    mensaje_bienvenida = (
        "¡Hola! Bienvenido a *Solar Barrio* ☀️.\n\n"
        "Estamos encantados de ayudarte a dar el salto a la energía limpia, "
        "ahorrar en tu factura y protegerte de los apagones.\n\n"
        "¿En qué podemos asesorarte hoy?"
    )
    await update.message.reply_text(
        mensaje_bienvenida,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(teclado, one_time_keyboard=True, resize_keyboard=True)
    )
    return MENU

async def manejar_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    opcion = update.message.text
    if "Ver Productos" in opcion:
        mensaje_kits = """¡Excelente elección! Aquí tienes nuestras soluciones estrella:

🟢 *Kit Ahorro:* Perfecto para reducir tu factura al máximo.
🔋 *Kit Anti-Apagones:* Baterías de respaldo para que tu casa siga con luz.
⚡ *Kit Independencia:* Libertad absoluta de la compañía eléctrica.

¿Te gustaría un estudio personalizado?"""
        await update.message.reply_text(
            mensaje_kits,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([['📊 Solicitar Estudio Gratuito']], resize_keyboard=True)
        )
        return MENU
    elif "Solicitar" in opcion:
        await update.message.reply_text(
            "¡Genial! Vamos a diseñar algo a tu medida. 🏠 Primero, ¿qué tipo de vivienda tienes?", 
            reply_markup=ReplyKeyboardMarkup([['Casa independiente', 'Adosado / Chalet'], ['Piso / Apartamento', 'Negocio / Local']], resize_keyboard=True)
        )
        return VIVIENDA
    return await start(update, context)

async def recibir_vivienda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['vivienda'] = update.message.text
    await update.message.reply_text(
        "Entendido. ⚡ ¿Cuál dirías que es tu problema principal ahora mismo?", 
        reply_markup=ReplyKeyboardMarkup([['Cortes de luz / Apagones', 'Facturas muy caras'], ['Ambas opciones']], resize_keyboard=True)
    )
    return PROBLEMA

async def recibir_problema(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['problema'] = update.message.text
    await update.message.reply_text(
        "Tomamos nota. 💡 ¿Cuál es tu gasto mensual aproximado en electricidad?", 
        reply_markup=ReplyKeyboardMarkup([['Menos de 50€', 'Entre 50€ y 100€'], ['Más de 100€', 'No lo sé seguro']], resize_keyboard=True)
    )
    return CONSUMO

async def recibir_consumo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['consumo'] = update.message.text
    await update.message.reply_text("¡Casi terminamos! 👤 Por favor, dime tu Nombre y Apellido para dirigirnos a ti:", reply_markup=ReplyKeyboardRemove())
    return NOMBRE

async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['nombre'] = update.message.text
    await update.message.reply_text(f"Un placer, {context.user_data['nombre']}. 📍 ¿En qué Barrio, Zona o Ciudad te encuentras?")
    return BARRIO

async def recibir_barrio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    datos = context.user_data
    datos['barrio'] = update.message.text
    
    usuario_tg_bruto = update.message.from_user.username
    usuario_final = f"@{usuario_tg_bruto}" if usuario_tg_bruto else f"Sin @ (Nombre: {update.message.from_user.first_name})"
    chat_id = str(update.message.chat_id)
    fecha_hoy = datetime.now().strftime("%d/%m/%Y")
    
    problema = datos.get('problema', '')
    consumo = datos.get('consumo', '')
    vivienda = datos.get('vivienda', '').lower()
    
    # Lógica inteligente
    if "Cortes" in problema or "Apagones" in problema:
        kit_recomendado = "Kit Anti-Apagones (Híbrido + Batería 5kWh)"
        precio = "5.490€"
        ahorro_est = "Hasta 85%"
    elif "Más de 100€" in consumo:
        kit_recomendado = "Kit Ahorro Total Plus (Alta Potencia)"
        precio = "4.200€"
        ahorro_est = "Hasta 70%"
    else:
        kit_recomendado = "Kit Ahorro Total Básico"
        precio = "3.100€"
        ahorro_est = "Hasta 60%"

    # Guardar en Render PostgreSQL
    try:
        conexion = psycopg2.connect(DATABASE_URL)
        cursor = conexion.cursor()
        cursor.execute('''
            INSERT INTO clientes (
                fecha_contacto, usuario_tg, chat_id, tipo_vivienda, problema, consumo, 
                nombre, barrio, telefono, estado_comercial, estado_obra, kit_asignado
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            fecha_hoy, usuario_final, chat_id, datos['vivienda'], datos['problema'], 
            datos['consumo'], datos['nombre'], datos['barrio'], "Pendiente", 
            "PRESUPUESTO ENVIADO AUTO", "PENDIENTE", kit_recomendado
        ))
        conexion.commit()
        conexion.close()
        print(f"✅ Nuevo Lead guardado en LA NUBE con Kit: {kit_recomendado}")
    except Exception as e:
        print(f"❌ Error guardando Lead en BD: {e}")

    # Mensaje detallado
    mensaje_presupuesto = (
        f"✅ *¡Estudio completado con éxito, {datos['nombre']}!*\n\n"
        f"Basado en los datos de tu {vivienda} en {datos['barrio']}, "
        f"nuestra Inteligencia Artificial ha diseñado la siguiente solución llave en mano para ti:\n\n"
        f"🔋 *Recomendación:* {kit_recomendado}\n"
        f"💰 *Presupuesto Estimado:* {precio} (IVA, licencias e instalación incl.)\n"
        f"💳 *Financiación 100%: Disponible desde el primer mes*\n"
        f"📉 *Ahorro estimado mensual:* {ahorro_est}\n\n"
        f"Nuestros ingenieros garantizan que esta es la mejor opción para resolver tu problema con: _{problema.lower()}_.\n\n"
        f"⚠️ *Nota Importante:* Este es un presupuesto inicial basado en tus respuestas. Para darte el precio cerrado al céntimo y firmar tu contrato, es necesario confirmar el estado del cuadro eléctrico y el tejado.\n\n"
        f"👷‍♂️ ¿Te gustaría que nuestro técnico visite tu domicilio para confirmar las medidas de forma totalmente *gratuita* y sin compromiso?"
    )

    teclado_venta = [
        [InlineKeyboardButton("✅ Sí, quiero la visita gratuita", callback_data=f"venta_si_{chat_id}")],
        [InlineKeyboardButton("❌ No por ahora, gracias", callback_data=f"venta_no_{chat_id}")]
    ]
    
    await update.message.reply_text(mensaje_presupuesto, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(teclado_venta))
    context.user_data.clear()
    return ConversationHandler.END

# --- 5. POST-VENTA ---
async def manejar_botones_venta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer() 
    datos_boton = query.data.split("_")
    respuesta, chat_id_cliente = datos_boton[1], datos_boton[2]

    try:
        conexion = psycopg2.connect(DATABASE_URL)
        cursor = conexion.cursor()

        if respuesta == "si":
            cursor.execute("UPDATE clientes SET estado_comercial = %s WHERE chat_id = %s", ("🔥 VISITA ACEPTADA", chat_id_cliente))
            conexion.commit()
            
            await query.edit_message_text(text=query.message.text + "\n\n*(Visita técnica aceptada ✅)*", parse_mode="Markdown")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="✅ *¡Fantástico!* 🎉\n\nPara que nuestro técnico pueda contactarte el día de la visita, **por favor, indícanos tu número de teléfono:**", 
                parse_mode="Markdown"
            )
            context.user_data['chat_id_cliente'] = chat_id_cliente
            conexion.close()
            return TELEFONO_POST
            
        elif respuesta == "no":
            cursor.execute("DELETE FROM clientes WHERE chat_id = %s", (chat_id_cliente,))
            conexion.commit()
            
            await query.edit_message_text(text=query.message.text + "\n\n*(Has declinado la propuesta ❌)*", parse_mode="Markdown")
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ *Datos borrados. ¡Gracias por tu tiempo!*", parse_mode="Markdown")
            conexion.close()
            return ConversationHandler.END

    except Exception as e:
        print(f"Error actualizando estado venta: {e}")

    return ConversationHandler.END

async def recibir_telefono_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telefono_cliente = update.message.text
    chat_id_cliente = context.user_data.get('chat_id_cliente') or str(update.message.chat_id)

    try:
        conexion = psycopg2.connect(DATABASE_URL)
        cursor = conexion.cursor()
        cursor.execute("UPDATE clientes SET telefono = %s WHERE chat_id = %s", (telefono_cliente, chat_id_cliente))
        conexion.commit()
        conexion.close()
    except Exception as e:
        print(f"Error guardando teléfono: {e}")

    await update.message.reply_text(
        "¡Gracias! 📞\n\nAhora, **escríbeme tu dirección completa** (Calle, número, código postal y localidad) para que el técnico sepa dónde ir:", 
        parse_mode="Markdown"
    )
    return DIRECCION_POST

async def recibir_direccion_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    direccion_cliente = update.message.text
    chat_id_cliente = context.user_data.get('chat_id_cliente') or str(update.message.chat_id)

    try:
        conexion = psycopg2.connect(DATABASE_URL)
        cursor = conexion.cursor()
        cursor.execute("UPDATE clientes SET direccion = %s WHERE chat_id = %s", (direccion_cliente, chat_id_cliente))
        conexion.commit()
        conexion.close()
    except Exception as e:
        print(f"Error guardando dirección: {e}")

    dias = obtener_proximos_dias_laborables(5)
    teclado_fechas = []
    nombres_dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    
    for d in dias:
        fecha_str = d.strftime("%d/%m/%Y")
        nombre_dia = nombres_dias[d.weekday()]
        texto_boton = f"{nombre_dia} {d.strftime('%d/%m')}"
        teclado_fechas.append([InlineKeyboardButton(texto_boton, callback_data=f"fecha_{fecha_str}_{chat_id_cliente}")])

    reply_markup = InlineKeyboardMarkup(teclado_fechas)
    await update.message.reply_text(
        "📍 *Dirección guardada.*\n\n🗓️ Para terminar, selecciona **qué día** prefieres que vaya nuestro técnico a hacer la visita:", 
        reply_markup=reply_markup, 
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def manejar_seleccion_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    datos = query.data.split("_")
    fecha_str = datos[1]
    chat_id_cliente = datos[2]
    
    horas_libres = obtener_horas_disponibles(fecha_str)
    
    if not horas_libres:
        await query.edit_message_text("Lo siento, nuestra agenda está completamente llena para ese día. Por favor, selecciona otra opción.")
        return

    teclado_horas = []
    fila_actual = []
    for h in horas_libres:
        fila_actual.append(InlineKeyboardButton(h, callback_data=f"hora_{fecha_str}_{h}_{chat_id_cliente}"))
        if len(fila_actual) == 2:
            teclado_horas.append(fila_actual)
            fila_actual = []
    if fila_actual:
        teclado_horas.append(fila_actual)

    reply_markup = InlineKeyboardMarkup(teclado_horas)
    await query.edit_message_text(
        f"Has seleccionado el **{fecha_str}**.\n\n⏰ Por favor, escoge una de las horas disponibles para la visita (duración aprox: 1h):",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def manejar_seleccion_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    datos = query.data.split("_")
    fecha_str = datos[1]
    hora_str = datos[2]
    chat_id_cliente = datos[3]
    
    cita_final = f"{fecha_str} {hora_str}"
    
    try:
        conexion = psycopg2.connect(DATABASE_URL)
        cursor = conexion.cursor()
        cursor.execute("UPDATE clientes SET visita_tecnica = %s WHERE chat_id = %s", (cita_final, chat_id_cliente))
        conexion.commit()
        conexion.close()
    except Exception as e:
        print(f"Error guardando hora en DB: {e}")

    mensaje_exito = f"✅ *¡Cita confirmada!*\n\nNuestro técnico te visitará el **{fecha_str}** a las **{hora_str}**.\n\n¡Gracias por confiar en Solar Barrio! ☀️"
    await query.edit_message_text(mensaje_exito, parse_mode="Markdown")

def main():
    app = Application.builder().token(TOKEN_BOT).build()
    
    conv_handler_principal = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.Regex(re.compile(r'^(hola|buenas|quiero)', re.IGNORECASE)), start)],
        states={
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_menu)],
            VIVIENDA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_vivienda)],
            PROBLEMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_problema)],
            CONSUMO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_consumo)],
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre)],
            BARRIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_barrio)],
        },
        fallbacks=[]
    )
    
    conv_handler_post_venta = ConversationHandler(
        entry_points=[CallbackQueryHandler(manejar_botones_venta, pattern="^venta_")],
        states={
            TELEFONO_POST: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_telefono_post)],
            DIRECCION_POST: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_direccion_post)]
        },
        fallbacks=[]
    )
    
    app.add_handler(conv_handler_principal)
    app.add_handler(conv_handler_post_venta)
    app.add_handler(CallbackQueryHandler(manejar_seleccion_fecha, pattern="^fecha_"))
    app.add_handler(CallbackQueryHandler(manejar_seleccion_hora, pattern="^hora_"))
    
    print("☀️ Bot Comercial Automático en línea (Conectado a PostgreSQL en Render)...")
    app.run_polling()

if __name__ == "__main__":
    main()
