# ============================ CONFIG ============================
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from flask import Flask
from threading import Thread

# Token del bot (deve essere impostato come variabile d'ambiente)
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN non trovato — imposta la variabile d'ambiente")

# Guild in cui registrare i comandi
GUILD_IDS = [1358713154116259892, 687741871757197312]

# Impostazioni di default
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

# ============================ HELPERS ============================
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

# ============================ EVENT CREATOR ============================
class EventCreator:
    def __init__(self, data, desc):
        self.data = data
        self.desc = desc
        self.roles = []
        self.selected_planes = {}
        self.selected_image = BACKGROUND_URL

    def to_active_roles(self):
        active = {}
        for r in self.roles:
            active[r] = {"plane": self.selected_planes.get(r, "Non Attivo"), "slots": DEFAULT_SLOTS, "users": []}
        return active

    async def finish_setup(self, interaction: discord.Interaction):
        active_roles = self.to_active_roles()
        bookings[self.data] = active_roles
        save_bookings()
        embed = generate_embed(self.data, self.desc, active_roles, self.selected_image)
        await interaction.response.send_message(embed=embed, view=BookingView(self))

# ============================ IMAGE SELECTION ============================
class ImageLinkModal(discord.ui.Modal, title="Inserisci link immagine personalizzata"):
    image_url = discord.ui.TextInput(label="URL immagine", placeholder="https://...", max_length=500)

    def __init__(self, creator):
        super().__init__()
        self.creator_ref = creator

    async def on_submit(self, interaction: discord.Interaction):
        self.creator_ref.selected_image = self.image_url.value.strip() or BACKGROUND_URL
        await interaction.response.send_message("🖼️ Immagine impostata. Ora puoi aggiungere ruoli o confermare l'evento.", view=AddRoleConfirmView(self.creator_ref), ephemeral=True)

class ImageSelectButton(discord.ui.Button):
    def __init__(self, creator, label, is_default=False):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.creator_ref = creator
        self.is_default = is_default

    async def callback(self, interaction: discord.Interaction):
        if self.is_default:
            self.creator_ref.selected_image = BACKGROUND_URL
            await interaction.response.send_message("🖼️ Usata immagine di default. Ora puoi aggiungere ruoli o confermare l'evento.", view=AddRoleConfirmView(self.creator_ref), ephemeral=True)
        else:
            await interaction.response.send_modal(ImageLinkModal(self.creator_ref))

class ImageSelectView(discord.ui.View):
    def __init__(self, creator):
        super().__init__(timeout=None)
        self.add_item(ImageSelectButton(creator, label="Usa immagine di default", is_default=True))
        self.add_item(ImageSelectButton(creator, label="Inserisci link immagine personalizzata", is_default=False))

# ============================ ROLE & PLANE SELECTION ============================
class RoleModal(discord.ui.Modal, title="Aggiungi Ruolo"):
    role_name = discord.ui.TextInput(label="Nome ruolo", placeholder="Es. Leader", max_length=50)

    def __init__(self, creator):
        super().__init__()
        self.creator_ref = creator

    async def on_submit(self, interaction: discord.Interaction):
        role = self.role_name.value.strip()
        if not role or len(self.creator_ref.roles) >= MAX_ROLES:
            await interaction.response.send_message(f"❌ Nome ruolo non valido o massimo ruoli raggiunto ({MAX_ROLES}).", ephemeral=True)
            return
        await interaction.response.send_message(f"✈️ Seleziona aereo per il ruolo **{role}**", view=PlaneSelectView(self.creator_ref, role), ephemeral=True)

class PlaneButton(discord.ui.Button):
    def __init__(self, creator, role, plane):
        super().__init__(label=plane, style=discord.ButtonStyle.primary)
        self.creator_ref = creator
        self.role = role
        self.plane = plane

    async def callback(self, interaction: discord.Interaction):
        if self.role not in self.creator_ref.roles:
            self.creator_ref.roles.append(self.role)
        self.creator_ref.selected_planes[self.role] = self.plane
        await interaction.response.send_message(f"✅ Ruolo **{self.role}** assegnato a **{self.plane}**. Puoi aggiungere un altro ruolo o confermare l'evento.", view=AddRoleConfirmView(self.creator_ref), ephemeral=True)

class PlaneSelectView(discord.ui.View):
    def __init__(self, creator, role):
        super().__init__(timeout=None)
        self.add_item(PlaneButton(creator, role, "F-16C"))
        self.add_item(PlaneButton(creator, role, "FA-18C"))

# ============================ ADD/CONFIRM ROLE ============================
class AddRoleButton(discord.ui.Button):
    def __init__(self, creator):
        super().__init__(label="Aggiungi Ruolo", style=discord.ButtonStyle.success)
        self.creator_ref = creator

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RoleModal(self.creator_ref))

class ConfirmEventButton(discord.ui.Button):
    def __init__(self, creator):
        super().__init__(label="Conferma Evento", style=discord.ButtonStyle.primary)
        self.creator_ref = creator

    async def callback(self, interaction: discord.Interaction):
        if not self.creator_ref.roles:
            await interaction.response.send_message("❌ Devi aggiungere almeno un ruolo prima di confermare.", ephemeral=True)
            return
        await self.creator_ref.finish_setup(interaction)

class AddRoleConfirmView(discord.ui.View):
    def __init__(self, creator):
        super().__init__(timeout=None)
        self.add_item(AddRoleButton(creator))
        self.add_item(ConfirmEventButton(creator))

# ============================ BOOKING VIEW ============================
class BookingButton(discord.ui.Button):
    def __init__(self, role, creator):
        super().__init__(label=role, style=discord.ButtonStyle.primary)
        self.role = role
        self.creator_ref = creator

    async def callback(self, interaction: discord.Interaction):
        active_roles = self.creator_ref.to_active_roles()
        for r, info in active_roles.items():
            if interaction.user.name in info["users"]:
                await interaction.response.send_message("❌ Hai già prenotato un ruolo!", ephemeral=True)
                return
        active_roles[self.role]["users"].append(interaction.user.name)
        embed = generate_embed(self.creator_ref.data, self.creator_ref.desc, active_roles, self.creator_ref.selected_image)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"✅ Ti sei prenotato per il ruolo **{self.role}**!", ephemeral=True)

class BookingView(discord.ui.View):
    def __init__(self, creator):
        super().__init__(timeout=None)
        for role in creator.roles:
            self.add_item(BookingButton(role, creator))

# ============================ COMANDO SLASH ============================
@bot.tree.command(name="prenotazioni", description="Crea un evento con ruoli, aerei e scelta immagine")
@app_commands.describe(data="Data della missione (es. 2025-09-22 18:00)", desc="Breve descrizione della missione")
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    creator = EventCreator(data, desc)
    view = ImageSelectView(creator)
    try:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("📸 Scegli un'immagine per l'evento:", view=view, ephemeral=True)
    except Exception as e:
        print(f"Errore invio view in /prenotazioni: {e}")
        try:
            await interaction.response.send_message("📸 Scegli un'immagine per l'evento:", view=view, ephemeral=True)
        except Exception as e2:
            print(f"Fallback inviato fallito: {e2}")
            try:
                await interaction.followup.send("❌ Errore interno durante l'apertura del setup. Riprova.", ephemeral=True)
            except Exception:
                pass

# ============================ SYNC E ON_READY ============================
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    for gid in GUILD_IDS:
        try:
            synced = await bot.tree.sync(guild=discord.Object(id=gid))
            print(f"🔄 Sincronizzati {len(synced)} comandi slash per guild {gid}: {[c.name for c in synced]}")
        except Exception as e:
            print(f"Errore sync per guild {gid}: {e}")

# ============================ WEB SERVER ============================
app = Flask('')

@app.route('/')
def home():
    return "Bot attivo!"

def run():
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run).start()

# ============================ AVVIO BOT ============================
bot.run(TOKEN)