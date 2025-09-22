import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from flask import Flask
from threading import Thread

# ---------------------------- CONFIG ----------------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN non trovato — imposta la variabile d'ambiente")

GUILD_IDS = [
    1358713154116259892,  # tuo server principale
    687741871757197312    # altro server
]

BACKGROUND_URL = "https://cdn.discordapp.com/attachments/710523786558046298/1403090934857728001/BCO.png"
DEFAULT_SLOTS = 4
MAX_ROLES = 5

# ---------------------------- BOT ----------------------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------- PERSISTENZA ----------------------------
if os.path.exists("prenotazioni.json"):
    with open("prenotazioni.json", "r") as f:
        bookings = json.load(f)
else:
    bookings = {}

def save_bookings():
    with open("prenotazioni.json", "w") as f:
        json.dump(bookings, f, indent=4)

# ---------------------------- FUNZIONE EMBED ----------------------------
def generate_embed(data: str, desc: str, active_roles: dict):
    embed = discord.Embed(title="📋 Prenotazioni Piloti", description=f"📅 Missione: {data}\n📝 {desc}", color=0x1abc9c)
    for role, info in active_roles.items():
        stato = "✅ Attivo" if info['plane'] != "Non Attivo" else "❌ Non Attivo"
        piloti = ", ".join(info['users']) if info['users'] else "Nessuno"
        embed.add_field(name=f"{role} ({len(info['users'])}/{info['slots']}) - {stato} - {info['plane']}", value=f"Prenotati: {piloti}", inline=False)
    embed.set_footer(text="Prenota cliccando i pulsanti qui sotto ✈️")
    embed.set_image(url=BACKGROUND_URL)
    return embed

# ---------------------------- BOTTONI ----------------------------
class BookingButton(discord.ui.Button):
    def __init__(self, role, data, desc, active_roles, plane):
        color = discord.ButtonStyle.success if active_roles[role]['plane'] == plane else discord.ButtonStyle.secondary
        super().__init__(label=role, style=color, disabled=active_roles[role]['plane'] != plane)
        self.role_name = role
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.plane = plane

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name
        already_in_role = None
        for r, info in self.active_roles.items():
            if user in info['users']:
                already_in_role = r
                break
        if already_in_role and already_in_role != self.role_name:
            await interaction.response.send_message(f"⚠️ Sei già prenotato in **{already_in_role}**! Rimuoviti prima.", ephemeral=True)
            return
        role_info = self.active_roles[self.role_name]
        if user in role_info['users']:
            role_info['users'].remove(user)
            save_bookings()
            await interaction.response.edit_message(embed=generate_embed(self.data, self.desc, self.active_roles), view=self.view)
            return
        if len(role_info['users']) >= role_info['slots']:
            await interaction.response.send_message(f"⚠️ {self.role_name} è già pieno!", ephemeral=True)
            return
        role_info['users'].append(user)
        save_bookings()
        await interaction.response.edit_message(embed=generate_embed(self.data, self.desc, self.active_roles), view=self.view)

class PlaneSelect(discord.ui.Select):
    def __init__(self, data, desc, active_roles):
        planes = list({info['plane'] for info in active_roles.values() if info['plane'] != 'Non Attivo'})
        options = [discord.SelectOption(label=p, value=p) for p in planes]
        super().__init__(placeholder="Seleziona aereo", min_values=1, max_values=1, options=options)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles

    async def callback(self, interaction: discord.Interaction):
        plane = self.values[0]
        view = discord.ui.View(timeout=None)
        for role in self.active_roles:
            view.add_item(BookingButton(role, self.data, self.desc, self.active_roles, plane))
        await interaction.response.edit_message(embed=generate_embed(self.data, self.desc, self.active_roles), view=view)

class PlaneSelectView(discord.ui.View):
    def __init__(self, data, desc, active_roles):
        super().__init__()
        self.add_item(PlaneSelect(data, desc, active_roles))

# ---------------------------- COMANDO SLASH ----------------------------
@bot.tree.command(name="prenotazioni", description="Crea un evento con ruoli dinamici")
@app_commands.describe(data="Data della missione", desc="Breve descrizione")
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    active_roles = {role: {'plane': 'FA-18C', 'slots': DEFAULT_SLOTS, 'users': []} for role in ['Barcap','Escort','Sead','Dead','Strike']}
    bookings[data] = active_roles
    save_bookings()
    view = PlaneSelectView(data, desc, active_roles)
    await interaction.response.send_message(embed=generate_embed(data, desc, active_roles), view=view)

# ---------------------------- ON_READY ----------------------------
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    try:
        for guild_id in GUILD_IDS:
            guild = discord.Object(id=guild_id)
            synced = await bot.tree.sync(guild=guild)
            print(f"🔄 Sincronizzati {len(synced)} comandi slash per la guild {guild_id}")
    except Exception as e:
        print(f"Errore sync: {e}")

# ---------------------------- WEB SERVER ----------------------------
app = Flask('')

@app.route('/')
def home():
    return "Bot attivo!"

def run():
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run).start()

# ---------------------------- AVVIO BOT ----------------------------
bot.run(TOKEN)
