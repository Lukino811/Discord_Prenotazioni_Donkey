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

# Guild in cui registrare i comandi (metti gli ID dei tuoi server)
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
    """Crea l'embed riepilogativo dell'evento con immagine e ruoli."""
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

# ============================ IMMAGINE: VIEW + MODAL ============================
class ImageLinkModal(discord.ui.Modal, title="Inserisci link immagine personalizzata"):
    image_url = discord.ui.TextInput(label="URL immagine", placeholder="https://...", max_length=500)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        # Salva l'immagine scelta e mostra la view per aggiungere ruoli/confermare
        self.parent.selected_image = self.image_url.value.strip() or BACKGROUND_URL
        await interaction.response.send_message("🖼️ Immagine impostata. Ora puoi aggiungere ruoli o confermare l'evento.", view=AddRoleConfirmView(self.parent), ephemeral=True)

class ImageSelectButton(discord.ui.Button):
    def __init__(self, parent, label, is_default=False):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.parent = parent
        self.is_default = is_default

    async def callback(self, interaction: discord.Interaction):
        if self.is_default:
            self.parent.selected_image = BACKGROUND_URL
            await interaction.response.send_message("🖼️ Usata immagine di default. Ora puoi aggiungere ruoli o confermare l'evento.", view=AddRoleConfirmView(self.parent), ephemeral=True)
        else:
            await interaction.response.send_modal(ImageLinkModal(self.parent))

class ImageSelectView(discord.ui.View):
    """View iniziale per scegliere immagine (default o link)"""
    def __init__(self, parent):
        super().__init__(timeout=None)
        self.parent = parent
        self.add_item(ImageSelectButton(parent, label="Usa immagine di default", is_default=True))
        self.add_item(ImageSelectButton(parent, label="Inserisci link immagine personalizzata", is_default=False))

# ============================ INPUT RUOLO + SELEZIONE AEREO ============================
class RoleModal(discord.ui.Modal, title="Aggiungi Ruolo"):
    role_name = discord.ui.TextInput(label="Nome ruolo", placeholder="Es. Leader", max_length=50)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        role = self.role_name.value.strip()
        if not role:
            await interaction.response.send_message("❌ Nome ruolo non valido.", ephemeral=True)
            return
        if len(self.parent.roles) >= MAX_ROLES:
            await interaction.response.send_message(f"❌ Massimo ruoli raggiunto ({MAX_ROLES}).", ephemeral=True)
            return
        # A questo punto mostriamo la view per scegliere l'aereo per questo ruolo
        await interaction.response.send_message(f"✈️ Seleziona aereo per il ruolo **{role}**", view=PlaneSelectView(self.parent, role), ephemeral=True)

class PlaneButton(discord.ui.Button):
    def __init__(self, parent, role, plane):
        super().__init__(label=plane, style=discord.ButtonStyle.primary)
        self.parent = parent
        self.role = role
        self.plane = plane

    async def callback(self, interaction: discord.Interaction):
        # Imposta l'aereo per il ruolo e aggiungi il ruolo alla lista
        if self.role in self.parent.roles:
            # ruolo già presente (aggiorna solo l'aereo)
            self.parent.selected_planes[self.role] = self.plane
        else:
            self.parent.roles.append(self.role)
            self.parent.selected_planes[self.role] = self.plane
        # Conferma e mostra di nuovo la view per aggiungere o confermare
        await interaction.response.send_message(f"✅ Ruolo **{self.role}** assegnato a **{self.plane}**.\nPuoi aggiungere un altro ruolo o confermare l'evento.", view=AddRoleConfirmView(self.parent), ephemeral=True)

class PlaneSelectView(discord.ui.View):
    """View che mostra i pulsanti per selezionare l'aereo per un ruolo appena creato."""
    def __init__(self, parent, role):
        super().__init__(timeout=None)
        self.parent = parent
        self.role = role
        # Multipli aerei richiesti: FA-18C e F-16C
        self.add_item(PlaneButton(parent, role, "F-16C"))
        self.add_item(PlaneButton(parent, role, "FA-18C"))

# ============================ VIEW AGGIUNGI/CONFERMA RUOLO ============================
class ConfirmEventButton(discord.ui.Button):
    def __init__(self, parent):
        super().__init__(label="Conferma Evento", style=discord.ButtonStyle.primary)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        # Controlli minimi: almeno 1 ruolo
        if not self.parent.roles:
            await interaction.response.send_message("❌ Devi aggiungere almeno un ruolo prima di confermare.", ephemeral=True)
            return
        await self.parent.finish_setup(interaction)

class AddRoleButton(discord.ui.Button):
    def __init__(self, parent):
        super().__init__(label="Aggiungi Ruolo", style=discord.ButtonStyle.success)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        # Apri la modal per inserire il nome del ruolo
        await interaction.response.send_modal(RoleModal(self.parent))

class AddRoleConfirmView(discord.ui.View):
    """View mostrata dopo scelta immagine: permette di aggiungere ruoli o confermare l'evento."""
    def __init__(self, parent):
        super().__init__(timeout=None)
        self.parent = parent
        self.add_item(AddRoleButton(parent))
        self.add_item(ConfirmEventButton(parent))

# ============================ CREAZIONE EVENTO E PRENOTAZIONI ============================
class BookingButton(discord.ui.Button):
    def __init__(self, role, data, desc, active_roles, plane, image_url):
        # Pulsante abilitato solo se role plane == plane corrente
        is_active = active_roles[role]["plane"] == plane
        style = discord.ButtonStyle.success if is_active else discord.ButtonStyle.secondary
        super().__init__(label=role, style=style, disabled=not is_active)
        self.role = role
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.plane = plane
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name
        # controlla se l'utente è già in un altro ruolo
        already = next((r for r,info in self.active_roles.items() if user in info["users"]), None)
        if already and already != self.role:
            await interaction.response.send_message(f"⚠️ Sei già prenotato in **{already}**. Rimuoviti prima.", ephemeral=True)
            return
        info = self.active_roles[self.role]
        if user in info["users"]:
            info["users"].remove(user)
            save_bookings()
            embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
            await interaction.response.edit_message(embed=embed, view=self.view)
            await interaction.followup.send(f"❌ Hai rimosso la tua prenotazione da **{self.role}**.", ephemeral=True)
            return
        if len(info["users"]) >= info["slots"]:
            await interaction.response.send_message(f"⚠️ {self.role} è pieno!", ephemeral=True)
            return
        info["users"].append(user)
        save_bookings()
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send(f"✅ Prenotazione in **{self.role}** confermata!", ephemeral=True)

class ChangePlaneButton(discord.ui.Button):
    def __init__(self, data, desc, active_roles, image_url):
        super().__init__(label="Cambia Aereo", style=discord.ButtonStyle.secondary)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        view = PlaneChoiceForBookingView(self.data, self.desc, self.active_roles, self.image_url)
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=view)

class BookingView(discord.ui.View):
    def __init__(self, data, desc, active_roles, plane, image_url):
        super().__init__(timeout=None)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.plane = plane
        self.image_url = image_url
        for role in active_roles:
            self.add_item(BookingButton(role, data, desc, active_roles, plane, image_url))
        self.add_item(ChangePlaneButton(data, desc, active_roles, image_url))

class PlaneChoiceForBookingView(discord.ui.View):
    def __init__(self, data, desc, active_roles, image_url):
        super().__init__(timeout=None)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.image_url = image_url
        # prendi tutti gli aerei attivi fra i ruoli
        planes = list({info["plane"] for info in active_roles.values() if info["plane"] != "Non Attivo"})
        for p in planes:
            self.add_item(PlanePickButton(self.data, self.desc, self.active_roles, p, self.image_url))

class PlanePickButton(discord.ui.Button):
    def __init__(self, data, desc, active_roles, plane, image_url):
        super().__init__(label=plane, style=discord.ButtonStyle.primary)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.plane = plane
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        view = BookingView(self.data, self.desc, self.active_roles, self.plane, self.image_url)
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=view)

# ============================ CREAZIONE EVENTO ============================
class EventCreator:
    """Oggetto helper che mantiene lo stato dell'evento durante il setup (data/desc/roles/planes/image)."""
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

# ============================ COMANDO SLASH ============================
@bot.tree.command(name="prenotazioni", description="Crea un evento con ruoli, aerei e scelta immagine")
@app_commands.describe(data="Data della missione (es. 2025-09-22 18:00)", desc="Breve descrizione della missione")
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    # inizializza il creator che terrà lo stato durante il setup
    creator = EventCreator(data, desc)
    # prepara la view per la scelta immagine
    view = ImageSelectView(creator)

    # Per evitare errori "Unknown interaction" e rispettare il limite di 3s,
    # deferiamo l'interazione e poi inviamo la view come followup.
    try:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("📸 Scegli un'immagine per l'evento:", view=view, ephemeral=True)
    except Exception as e:
        # fallback: prova a inviare direttamente (se la defer è fallita)
        print(f"Errore invio view in /prenotazioni: {e}")
        try:
            await interaction.response.send_message("📸 Scegli un'immagine per l'evento:", view=view, ephemeral=True)
        except Exception as e2:
            print(f"Fallback inviato fallito: {e2}")
            # ultima risorsa: invia messaggio pubblico di errore
            try:
                await interaction.followup.send("❌ Errore interno durante l'apertura del setup. Riprova.", ephemeral=True)
            except Exception:
                pass

# registra il comando localmente per ogni guild per comparsa immediata
for gid in GUILD_IDS:
    try:
        bot.tree.add_command(prenotazioni, guild=discord.Object(id=gid))
        print(f"🔧 Command /prenotazioni aggiunto localmente per guild {gid}")
    except Exception as e:
        print(f"Errore add_command per guild {gid}: {e}")

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

# ============================ WEB SERVER PER RENDER ============================
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
