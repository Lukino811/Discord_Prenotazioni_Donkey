# ============================ CONFIG ============================
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from flask import Flask
from threading import Thread

# Ottieni il token del bot dall'ambiente
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN non trovato — imposta la variabile d'ambiente")

GUILD_IDS = [1358713154116259892, 687741871757197312]
BACKGROUND_URL = "https://cdn.discordapp.com/attachments/710523786558046298/1403090934857728001/BCO.png"
MAX_ROLES = 5
DEFAULT_SLOTS = 4

# ============================ BOT ============================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================ PERSISTENZA ============================
if os.path.exists("prenotazioni.json"):
    with open("prenotazioni.json", "r") as f:
        bookings = json.load(f)
else:
    bookings = {}

def save_bookings():
    with open("prenotazioni.json", "w") as f:
        json.dump(bookings, f, indent=4)

# ============================ EMBED ============================
def generate_embed(data: str, desc: str, active_roles: dict, image_url: str = BACKGROUND_URL):
    embed = discord.Embed(title="📋 Prenotazioni Piloti",
                          description=f"📅 Missione: {data}\n📝 {desc}",
                          color=0x1abc9c)
    for role, info in active_roles.items():
        stato = "✅ Attivo" if info["plane"] != "Non Attivo" else "❌ Non Attivo"
        piloti = ", ".join(info["users"]) if info["users"] else "Nessuno"
        embed.add_field(name=f"{role} ({len(info['users'])}/{info['slots']}) - {stato} - {info['plane']}",
                        value=f"Prenotati: {piloti}", inline=False)
    embed.set_footer(text="Prenota cliccando i pulsanti qui sotto ✈️")
    embed.set_image(url=image_url)
    return embed

# ============================ SELEZIONE IMMAGINE ============================
class ImageLinkModal(discord.ui.Modal, title="Inserisci link immagine personalizzata"):
    image_url = discord.ui.TextInput(label="URL immagine", placeholder="https://...", max_length=500)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.selected_image = self.image_url.value.strip() or BACKGROUND_URL
        await interaction.response.send_message("📸 Immagine personalizzata impostata!", ephemeral=True)
        await self.parent_view.continue_setup(interaction)

class ImageSelectButton(discord.ui.Button):
    def __init__(self, parent_view, label, url=None):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
        self.url = url

    async def callback(self, interaction: discord.Interaction):
        if self.url:
            self.parent_view.selected_image = self.url
            await interaction.response.send_message("🖼️ Usata immagine di default!", ephemeral=True)
            await self.parent_view.continue_setup(interaction)
        else:
            await interaction.response.send_modal(ImageLinkModal(self.parent_view))

class ImageSelectView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=None)
        self.add_item(ImageSelectButton(parent_view, label="Usa immagine di default", url=BACKGROUND_URL))
        self.add_item(ImageSelectButton(parent_view, label="Inserisci link immagine personalizzata"))

# ============================ BOTTONI E VIEW PRENOTAZIONE ============================
class BookingButton(discord.ui.Button):
    def __init__(self, role, data, desc, active_roles, plane, image_url):
        is_active = active_roles[role]["plane"] == plane
        color = discord.ButtonStyle.success if is_active else discord.ButtonStyle.secondary
        super().__init__(label=role, style=color, disabled=not is_active)
        self.role_name = role
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.plane = plane
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name
        already_in_role = next((r for r, info in self.active_roles.items() if user in info["users"]), None)

        if already_in_role and already_in_role != self.role_name:
            await interaction.response.send_message(f"⚠️ Sei già prenotato in **{already_in_role}**! Rimuoviti prima da quel ruolo.", ephemeral=True)
            return

        role_info = self.active_roles[self.role_name]

        if user in role_info["users"]:
            role_info["users"].remove(user)
            save_bookings()
            embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
            await interaction.response.edit_message(embed=embed, view=self.view)
            await interaction.followup.send(f"❌ Hai rimosso la tua prenotazione da **{self.role_name}**.", ephemeral=True)
            return

        if len(role_info["users"]) >= role_info["slots"]:
            await interaction.response.send_message(f"⚠️ {self.role_name} è già pieno!", ephemeral=True)
            return

        role_info["users"].append(user)
        save_bookings()
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send(f"✅ Prenotazione in **{self.role_name}** confermata!", ephemeral=True)

class ChangePlaneButton(discord.ui.Button):
    def __init__(self, data, desc, active_roles, image_url):
        super().__init__(label="Cambia Aereo", style=discord.ButtonStyle.secondary)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        view = PlaneSelectView(self.data, self.desc, self.active_roles, self.image_url)
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=view)

class BookingView(discord.ui.View):
    def __init__(self, data, desc, active_roles, plane, image_url):
        super().__init__(timeout=None)
        for role in active_roles:
            self.add_item(BookingButton(role, data, desc, active_roles, plane, image_url))
        self.add_item(ChangePlaneButton(data, desc, active_roles, image_url))

class PlaneSelect(discord.ui.Select):
    def __init__(self, data, desc, active_roles, image_url):
        planes = list({info["plane"] for info in active_roles.values() if info["plane"] != "Non Attivo"})
        options = [discord.SelectOption(label=p, value=p) for p in planes]
        super().__init__(placeholder="Seleziona l'aereo con cui vuoi volare", min_values=1, max_values=1, options=options)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        chosen_plane = self.values[0]
        for role in self.active_roles:
            if self.active_roles[role]["plane"] != "Non Attivo":
                self.active_roles[role]["plane"] = chosen_plane
        view = BookingView(self.data, self.desc, self.active_roles, chosen_plane, self.image_url)
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=view)

# ============================ PLANE SELECT VIEW ============================
class PlaneSelectView(discord.ui.View):
    def __init__(self, data, desc, active_roles, image_url):
        super().__init__()
        self.add_item(PlaneSelect(data, desc, active_roles, image_url))

# ============================ MODALI RUOLI ============================
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
        await interaction.response.send_message(f"Ruolo **{role_name}** aggiunto. Seleziona l'aereo:",
                                               view=SetPlaneButtonView(self.parent_view, role_name), ephemeral=True)

class PlaneSelectForRole(discord.ui.Select):
    def __init__(self, parent_view, role_name):
        options = [discord.SelectOption(label="F-16C", value="F-16C"),
                   discord.SelectOption(label="FA-18C", value="FA-18C"),
                   discord.SelectOption(label="Non Attivo", value="Non Attivo")]
        super().__init__(placeholder=f"Scegli aereo per {role_name}", min_values=1, max_values=1, options=options)
        self.parent_view = parent_view
        self.role_name = role_name

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.selected_planes[self.role_name] = self.values[0]
        await interaction.response.send_message(f"Aereo per ruolo **{self.role_name}** impostato su **{self.values[0]}**", ephemeral=True)
        if len(self.parent_view.roles) < MAX_ROLES:
            await interaction.followup.send("Vuoi aggiungere un nuovo ruolo?", view=AddRoleButtonView(self.parent_view), ephemeral=True)
        else:
            await self.parent_view.finish_setup(interaction)

class SetPlaneButton(discord.ui.Button):
    def __init__(self, parent_view, role_name):
        super().__init__(label="Imposta Aereo", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
        self.role_name = role_name

    async def callback(self, interaction: discord.Interaction):
        view = discord.ui.View()
        view.add_item(PlaneSelectForRole(self.parent_view, self.role_name))
        await interaction.response.send_message(f"Seleziona l'aereo per il ruolo **{self.role_name}**:", view=view, ephemeral=True)

class SetPlaneButtonView(discord.ui.View):
    def __init__(self, parent_view, role_name):
        super().__init__(timeout=None)
        self.add_item(SetPlaneButton(parent_view, role_name))

class AddRoleButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="Aggiungi Ruolo", style=discord.ButtonStyle.success)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RoleInput(self.parent_view))

class ConfirmEventButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="Conferma Evento", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.parent_view.finish_setup(interaction)

class AddRoleButtonView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=None)
        self.add_item(AddRoleButton(parent_view))
        self.add_item(ConfirmEventButton(parent_view))

# ============================ EVENT SETUP ============================
class EventSetupView:
    def __init__(self, data, desc):
        self.data = data
        self.desc = desc
        self.roles = []
        self.selected_planes = {}
        self.selected_image = BACKGROUND_URL

    async def start(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RoleInput(self))

    async def continue_setup(self, interaction: discord.Interaction):
        await interaction.response.send_message("Prosegui con la creazione dell'evento", view=AddRoleButtonView(self), ephemeral=True)

    async def finish_setup(self, interaction: discord.Interaction):
        active_roles = {}
        for role in self.roles:
            plane_choice = self.selected_planes.get(role, "Non Attivo")
            active_roles[role] = {"plane": plane_choice, "slots": DEFAULT_SLOTS, "users": []}
        bookings[self.data] = active_roles
        save_bookings()
        plane_view = PlaneSelectView(self.data, self.desc, active_roles, self.selected_image)
        embed = generate_embed(self.data, self.desc, active_roles, self.selected_image)
        await interaction.followup.send(embed=embed, view=plane_view)

# ============================ COMANDO SLASH ============================
@app_commands.command(name="prenotazioni", description="Crea un evento con ruoli e aerei")
@app_commands.describe(data="Data della missione (es. 2025-09-22 18:00)", desc="Breve descrizione della missione")
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup = EventSetupView(data, desc)
    # Apri la selezione ruoli
    await setup.start(interaction)

for guild_id in GUILD_IDS:
    bot.tree.add_command(prenotazioni, guild=discord.Object(id=guild_id))

# ============================ ON_READY ============================
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    try:
        for guild_id in GUILD_IDS:
            synced = await bot.tree.sync(guild=discord.Object(id=guild_id))
            print(f"🔄 Sincronizzati {len(synced)} comandi slash per guild {guild_id}")
    except Exception as e:
        print(f"Errore sync: {e}")

# ============================ WEB SERVER ============================
app = Flask('')

@app.route('/')
def home():
    return "Bot attivo!"

def run():
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run, daemon=False).start()

# ============================ AVVIO BOT ============================
bot.run(TOKEN)
