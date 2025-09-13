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

# Lista di server autorizzati
GUILD_IDS = [
    1358713154116259892,  # tuo server di test
    687741871757197312    # altro server
]

BACKGROUND_URL = "https://cdn.discordapp.com/attachments/710523786558046298/1403090934857728001/BCO.png"
roles_template = {
    "Barcap": {"slots": 4},
    "Escort": {"slots": 4},
    "Sead": {"slots": 4},
    "Dead": {"slots": 4},
    "Strike": {"slots": 4}
}

available_planes = ["FA-18C", "F-16C"]

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

# ---------------------------- EMBED ----------------------------
def generate_embed(data: str, desc: str, active_roles: dict, user_planes: dict):
    embed = discord.Embed(
        title="📋 Prenotazioni Piloti",
        description=f"📅 Missione: {data}\n📝 {desc}",
        color=0x1abc9c
    )
    for role, info in active_roles.items():
        stato = "✅ Attivo" if info["plane"] != "Non Attivo" else "❌ Non Attivo"
        piloti_text = ", ".join(info["users"]) if info["users"] else "Nessuno"
        embed.add_field(
            name=f"{role} ({len(info['users'])}/{info['slots']}) - {stato} - {info['plane']}",
            value=f"Prenotati: {piloti_text}",
            inline=False
        )
    embed.set_footer(text="Seleziona il ruolo compatibile con il tuo aereo ✈️")
    embed.set_image(url=BACKGROUND_URL)
    return embed

# ---------------------------- BOTTONI ----------------------------
class BookingButton(discord.ui.Button):
    def __init__(self, role, data, desc, active_roles, user_planes, user_plane_choice):
        self.role_name = role
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.user_planes = user_planes
        self.user_plane_choice = user_plane_choice
        role_plane = active_roles[role]["plane"]
        color = discord.ButtonStyle.success if role_plane != "Non Attivo" else discord.ButtonStyle.secondary
        disabled = role_plane == "Non Attivo" or role_plane != user_plane_choice
        super().__init__(label=role, style=color, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name
        # Rimuove l'utente da eventuali altri ruoli
        for r, info in self.active_roles.items():
            if user in info["users"]:
                info["users"].remove(user)

        role_info = self.active_roles[self.role_name]

        if len(role_info["users"]) >= role_info["slots"]:
            await interaction.response.send_message(f"⚠️ {self.role_name} è pieno!", ephemeral=True)
            return

        # Aggiorna aereo e aggiunge al ruolo
        self.user_planes[user] = self.user_plane_choice
        role_info["users"].append(user)

        save_bookings()
        embed = generate_embed(self.data, self.desc, self.active_roles, self.user_planes)
        # Aggiunge anche i pulsanti extra (Cambia aereo / Allega file)
        view = BookingView(self.data, self.desc, self.active_roles, self.user_planes, self.user_plane_choice)
        view.add_item(ExtraButtons(self.data, self.desc, self.active_roles, self.user_planes))
        await interaction.response.edit_message(embed=embed, view=view)
        await interaction.followup.send(f"✅ Prenotazione confermata in **{self.role_name}**.", ephemeral=True)

class BookingView(discord.ui.View):
    def __init__(self, data, desc, active_roles, user_planes, user_plane_choice):
        super().__init__(timeout=None)
        for role in active_roles:
            self.add_item(BookingButton(role, data, desc, active_roles, user_planes, user_plane_choice))
        self.add_item(ExtraButtons(data, desc, active_roles, user_planes))

# ---------------------------- PULSANTI EXTRA ----------------------------
class ExtraButtons(discord.ui.Button):
    def __init__(self, data, desc, active_roles, user_planes):
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.user_planes = user_planes
        super().__init__(label="Extra", style=discord.ButtonStyle.secondary, disabled=True)

    @discord.ui.button(label="Cambia Aereo", style=discord.ButtonStyle.primary)
    async def change_plane(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PlaneSelectView(self.data, self.desc, self.active_roles, self.user_planes)
        embed = generate_embed(self.data, self.desc, self.active_roles, self.user_planes)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Allega File", style=discord.ButtonStyle.secondary)
    async def attach_file(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📎 Invia qui il file o immagine da allegare.", ephemeral=True)

# ---------------------------- SELEZIONE AEREO ----------------------------
class PlaneSelect(discord.ui.Select):
    def __init__(self, data, desc, active_roles, user_planes):
        options = [discord.SelectOption(label=p, value=p) for p in available_planes]
        super().__init__(placeholder="Seleziona l'aereo con cui voli", min_values=1, max_values=1, options=options)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.user_planes = user_planes

    async def callback(self, interaction: discord.Interaction):
        user_plane_choice = self.values[0]
        view = BookingView(self.data, self.desc, self.active_roles, self.user_planes, user_plane_choice)
        embed = generate_embed(self.data, self.desc, self.active_roles, self.user_planes)
        await interaction.response.edit_message(embed=embed, view=view)

class PlaneSelectView(discord.ui.View):
    def __init__(self, data, desc, active_roles, user_planes):
        super().__init__()
        self.add_item(PlaneSelect(data, desc, active_roles, user_planes))

# ---------------------------- CREAZIONE EVENTO ----------------------------
class RolePlaneSelect(discord.ui.Select):
    def __init__(self, role, selected_planes):
        options = [
            discord.SelectOption(label="FA-18C", value="FA-18C"),
            discord.SelectOption(label="F-16C", value="F-16C"),
            discord.SelectOption(label="Non Attivo", value="Non Attivo")
        ]
        super().__init__(placeholder=f"Scegli aereo per {role}", min_values=1, max_values=1, options=options)
        self.role = role
        self.selected_planes = selected_planes

    async def callback(self, interaction: discord.Interaction):
        self.selected_planes[self.role] = self.values[0]
        await interaction.response.send_message(f"Aereo per {self.role} impostato su {self.values[0]}", ephemeral=True)

class EventSetupView(discord.ui.View):
    def __init__(self, roles, data, desc):
        super().__init__(timeout=None)
        self.selected_planes = {}
        self.data = data
        self.desc = desc
        self.role_views = []

        role_list = list(roles)
        for i in range(0, len(role_list), 5):
            view = discord.ui.View(timeout=None)
            for role in role_list[i:i+5]:
                view.add_item(RolePlaneSelect(role, self.selected_planes))
            self.role_views.append(view)

        self.confirm_view = ConfirmButtonView(self)

class ConfirmButtonView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=None)
        self.parent_view = parent_view

    @discord.ui.button(label="Conferma Evento", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        active_roles = {}
        for role, info in roles_template.items():
            plane_choice = self.parent_view.selected_planes.get(role, "Non Attivo")
            active_roles[role] = {
                "plane": plane_choice,
                "slots": info["slots"],
                "users": []
            }
        bookings[self.parent_view.data] = active_roles
        save_bookings()
        user_planes = {}
        plane_view = PlaneSelectView(self.parent_view.data, self.parent_view.desc, active_roles, user_planes)
        embed = generate_embed(self.parent_view.data, self.parent_view.desc, active_roles, user_planes)
        await interaction.response.send_message(embed=embed, view=plane_view)

# ---------------------------- COMANDO SLASH ----------------------------
@app_commands.command(name="prenotazioni", description="Crea un evento con ruoli e aerei")
@app_commands.describe(
    data="Data della missione (es. 2025-09-12 18:00)",
    desc="Breve descrizione della missione"
)
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup_view = EventSetupView(roles_template.keys(), data, desc)
    for i, view in enumerate(setup_view.role_views):
        if i == 0:
            await interaction.response.send_message("Seleziona aerei per i ruoli:", view=view, ephemeral=True)
        else:
            await interaction.followup.send("Seleziona aerei per i ruoli:", view=view, ephemeral=True)
    await interaction.followup.send(
        "Conferma l'evento quando hai completato la scelta degli aerei:", view=setup_view.confirm_view, ephemeral=True
    )

bot.tree.add_command(prenotazioni, guild=discord.Object(id=GUILD_ID))

# ---------------------------- ON_READY ----------------------------
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"🔄 Sincronizzati {len(synced)} comandi slash")
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

