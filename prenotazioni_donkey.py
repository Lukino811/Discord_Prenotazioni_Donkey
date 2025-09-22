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
MAX_ROLES = 5
DEFAULT_SLOTS = 4

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
    embed = discord.Embed(
        title="📋 Prenotazioni Piloti",
        description=f"📅 Missione: {data}\n📝 {desc}",
        color=0x1abc9c
    )
    for role, info in active_roles.items():
        stato = "✅ Attivo" if info["plane"] != "Non Attivo" else "❌ Non Attivo"
        piloti = ", ".join(info["users"]) if info["users"] else "Nessuno"
        embed.add_field(
            name=f"{role} ({len(info['users'])}/{info['slots']}) - {stato} - {info['plane']}",
            value=f"Prenotati: {piloti}",
            inline=False
        )
    embed.set_footer(text="Prenota cliccando i pulsanti qui sotto ✈️")
    embed.set_image(url=BACKGROUND_URL)
    return embed

# ---------------------------- BOTTONI ----------------------------
class BookingButton(discord.ui.Button):
    def __init__(self, role, data, desc, active_roles, plane):
        is_active = active_roles[role]["plane"] == plane
        color = discord.ButtonStyle.success if is_active else discord.ButtonStyle.secondary
        super().__init__(label=role, style=color, disabled=not is_active)
        self.role_name = role
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.plane = plane

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name
        already_in_role = None
        for r, info in self.active_roles.items():
            if user in info["users"]:
                already_in_role = r
                break

        if already_in_role and already_in_role != self.role_name:
            await interaction.response.send_message(
                f"⚠️ Sei già prenotato in **{already_in_role}**! "
                "Rimuoviti prima da quel ruolo per prenotarti qui.",
                ephemeral=True
            )
            return

        role_info = self.active_roles[self.role_name]

        if user in role_info["users"]:
            role_info["users"].remove(user)
            save_bookings()
            embed = generate_embed(self.data, self.desc, self.active_roles)
            await interaction.response.edit_message(embed=embed, view=self.view)
            await interaction.followup.send(
                f"❌ Hai rimosso la tua prenotazione da **{self.role_name}**.",
                ephemeral=True
            )
            return

        if len(role_info["users"]) >= role_info["slots"]:
            await interaction.response.send_message(
                f"⚠️ {self.role_name} è già pieno!",
                ephemeral=True
            )
            return

        role_info["users"].append(user)
        save_bookings()
        embed = generate_embed(self.data, self.desc, self.active_roles)
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send(
            f"✅ Prenotazione in **{self.role_name}** confermata!",
            ephemeral=True
        )

class ChangePlaneButton(discord.ui.Button):
    def __init__(self, data, desc, active_roles):
        super().__init__(label="Cambia Aereo", style=discord.ButtonStyle.secondary)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles

    async def callback(self, interaction: discord.Interaction):
        view = PlaneSelectView(self.data, self.desc, self.active_roles)
        embed = generate_embed(self.data, self.desc, self.active_roles)
        await interaction.response.edit_message(embed=embed, view=view)

# ---------------------------- VIEW ----------------------------
class BookingView(discord.ui.View):
    def __init__(self, data, desc, active_roles, plane):
        super().__init__(timeout=None)
        for role in active_roles:
            self.add_item(BookingButton(role, data, desc, active_roles, plane))
        self.add_item(ChangePlaneButton(data, desc, active_roles))

class PlaneSelect(discord.ui.Select):
    def __init__(self, data, desc, active_roles):
        planes = list({info["plane"] for info in active_roles.values() if info["plane"] != "Non Attivo"})
        options = [discord.SelectOption(label=p, value=p) for p in planes]
        super().__init__(placeholder="Seleziona l'aereo con cui vuoi volare", min_values=1, max_values=1, options=options)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles

    async def callback(self, interaction: discord.Interaction):
        chosen_plane = self.values[0]
        embed = generate_embed(self.data, self.desc, self.active_roles)
        view = BookingView(self.data, self.desc, self.active_roles, chosen_plane)
        await interaction.response.edit_message(embed=embed, view=view)

class PlaneSelectView(discord.ui.View):
    def __init__(self, data, desc, active_roles):
        super().__init__()
        self.add_item(PlaneSelect(data, desc, active_roles))

# ---------------------------- CREAZIONE EVENTO DINAMICO CORRETTA ----------------------------
class RoleInput(discord.ui.Modal, title="Aggiungi Ruolo"):
    role_name = discord.ui.TextInput(label="Nome ruolo", placeholder="Scrivi il nome del ruolo", max_length=50)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        if len(self.parent_view.roles) >= MAX_ROLES:
            await interaction.response.send_message("Hai raggiunto il limite di ruoli.", ephemeral=True)
            return

        role_name = self.role_name.value.strip()
        self.parent_view.roles.append(role_name)
        await interaction.response.send_modal(PlaneInput(self.parent_view, role_name))

class PlaneInput(discord.ui.Modal, title="Seleziona Aereo per il Ruolo"):
    plane_name = discord.ui.TextInput(
        label="Aereo",
        placeholder="Scrivi F-16C o FA-18C o Non Attivo",
        max_length=10
    )

    def __init__(self, parent_view, role_name):
        super().__init__()
        self.parent_view = parent_view
        self.role_name = role_name
        self.add_item(self.plane_name)

    async def on_submit(self, interaction: discord.Interaction):
        plane = self.plane_name.value.strip()
        if plane not in ["F-16C", "FA-18C", "Non Attivo"]:
            await interaction.response.send_message(
                "⚠️ Inserisci un valore valido: F-16C, FA-18C o Non Attivo",
                ephemeral=True
            )
            return

        self.parent_view.selected_planes[self.role_name] = plane
        await interaction.response.send_message(
            f"Ruolo **{self.role_name}** impostato con aereo **{plane}**",
            ephemeral=True
        )

        if len(self.parent_view.roles) < MAX_ROLES:
            await interaction.followup.send_modal(RoleInput(self.parent_view))
        else:
            await self.parent_view.finish_setup(interaction)

class EventSetupView:
    def __init__(self, data, desc):
        self.roles = []
        self.selected_planes = {}
        self.data = data
        self.desc = desc

    async def start(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RoleInput(self))

    async def finish_setup(self, interaction: discord.Interaction):
        active_roles = {}
        for role in self.roles:
            plane = self.selected_planes.get(role, "Non Attivo")
            active_roles[role] = {"plane": plane, "slots": DEFAULT_SLOTS, "users": []}

        bookings[self.data] = active_roles
        save_bookings()

        embed = generate_embed(self.data, self.desc, active_roles)
        view = PlaneSelectView(self.data, self.desc, active_roles)
        await interaction.followup.send(embed=embed, view=view)

# ---------------------------- COMANDO SLASH ----------------------------
@app_commands.command(name="prenotazioni", description="Crea un evento con ruoli e aerei")
@app_commands.describe(
    data="Data della missione (es. 2025-09-12 18:00)",
    desc="Breve descrizione della missione"
)
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup = EventSetupView(data, desc)
    await setup.start(interaction)

for guild_id in GUILD_IDS:
    bot.tree.add_command(prenotazioni, guild=discord.Object(id=guild_id))

# ---------------------------- ON_READY ----------------------------
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    try:
        for guild_id in GUILD_IDS:
            synced = await bot.tree.sync(guild=discord.Object(id=guild_id))
            print(f"🔄 Sincronizzati {len(synced)} comandi slash per guild {guild_id}")
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
