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

roles_template = {
    "Barcap": {"slots": 4},
    "Escort": {"slots": 4},
    "Sead": {"slots": 4},
    "Dead": {"slots": 4},
    "Strike": {"slots": 4}
}

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
        view.add_item(ChangePlaneButton(self.data, self.desc, self.active_roles))
        await interaction.response.edit_message(embed=embed, view=view)

class PlaneSelectView(discord.ui.View):
    def __init__(self, data, desc, active_roles):
        super().__init__()
        self.add_item(PlaneSelect(data, desc, active_roles))

# ---------------------------- CREAZIONE EVENTO ----------------------------
# Flow aggiornato: ruoli dinamici (max 5), modal per nome ruolo + scelta aereo immediata

MAX_ROLES = 5
DEFAULT_SLOTS = 4

class RoleNameModal(discord.ui.Modal, title="Inserisci nome ruolo"):
    role_input = discord.ui.TextInput(label="Nome ruolo", placeholder="Es. Alpha, Bravo, CAP Sud", max_length=100)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        role_name = self.role_input.value.strip()
        if not role_name:
            await interaction.response.send_message("Nome ruolo non valido.", ephemeral=True)
            return

        # Controlli: duplicati e limite
        if role_name in self.parent_view.selected_planes:
            await interaction.response.send_message(f"Ruolo **{role_name}** già aggiunto.", ephemeral=True)
            return

        if len(self.parent_view.selected_planes) >= MAX_ROLES:
            await interaction.response.send_message("Hai raggiunto il limite di ruoli.", ephemeral=True)
            return

        # Temporaneamente aggiungiamo con "Non Attivo" finché l'utente non sceglie l'aereo
        self.parent_view.selected_planes[role_name] = "Non Attivo"

        # Aggiorna il messaggio principale di setup
        await self.parent_view.update_setup_message()

        # Apri subito la select per scegliere l'aereo per questo ruolo
        view = discord.ui.View(timeout=None)
        view.add_item(RolePlaneSelect(role_name, self.parent_view))
        await interaction.response.send_message(f"Scegli l'aereo per **{role_name}**:", view=view, ephemeral=True)


class RolePlaneSelect(discord.ui.Select):
    def __init__(self, role, parent_view):
        options = [
            discord.SelectOption(label="FA-18C", value="FA-18C"),
            discord.SelectOption(label="F-16C", value="F-16C"),
            discord.SelectOption(label="Non Attivo", value="Non Attivo")
        ]
        super().__init__(placeholder=f"Scegli aereo per {role}", min_values=1, max_values=1, options=options)
        self.role = role
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        chosen = self.values[0]
        self.parent_view.selected_planes[self.role] = chosen
        await interaction.response.send_message(f"Aereo per **{self.role}** impostato su **{chosen}**", ephemeral=True)
        await self.parent_view.update_setup_message()


class EventSetupView(discord.ui.View):
    def __init__(self, roles, data: str, desc: str):
        super().__init__(timeout=None)
        self.roles = list(roles)  # Salva i ruoli in una lista
        self.data = data
        self.desc = desc
        self.selected_planes = {}
        self.role_views = []

        # Crea le view dei ruoli
        for i in range(0, len(self.roles), 5):
            view = discord.ui.View(timeout=None)
            for role in self.roles[i:i+5]:
                view.add_item(RolePlaneSelect(role, self))  # <-- qui deve esserci self
            self.role_views.append(view)

        self.confirm_view = ConfirmButtonView(self)



    async def update_setup_message(self):
        # Aggiorna il contenuto dell'embed/messaggio che mostra i ruoli scelti
        content = f"📅 Missione: **{self.data}**\n📝 {self.desc}\n\n"
        if not self.selected_planes:
            content += "Nessun ruolo aggiunto. Clicca `Aggiungi ruolo` per iniziare."
        else:
            content += "**Ruoli configurati:**\n"
            for r, p in self.selected_planes.items():
                content += f"- {r} → {p}\n"
            if len(self.selected_planes) >= MAX_ROLES:
                content += "\n⚠️ Hai raggiunto il limite di ruoli."

        if self.message:
            try:
                await self.message.edit(content=content, view=self)
            except Exception:
                pass


class AddRoleButton(discord.ui.Button):
    def __init__(self, parent_view: EventSetupView):
        super().__init__(label="Aggiungi ruolo", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if len(self.parent_view.selected_planes) >= MAX_ROLES:
            await interaction.response.send_message("Hai raggiunto il limite di ruoli", ephemeral=True)
            return
        modal = RoleNameModal(self.parent_view)
        await interaction.response.send_modal(modal)


class RemoveRoleButton(discord.ui.Button):
    def __init__(self, parent_view: EventSetupView):
        super().__init__(label="Rimuovi ruolo", style=discord.ButtonStyle.secondary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if not self.parent_view.selected_planes:
            await interaction.response.send_message("Non ci sono ruoli da rimuovere.", ephemeral=True)
            return

        view = discord.ui.View(timeout=None)
        options = [discord.SelectOption(label=r, value=r) for r in self.parent_view.selected_planes.keys()]
        sel = discord.ui.Select(placeholder="Seleziona ruolo da rimuovere", min_values=1, max_values=1, options=options)

        async def sel_cb(inter: discord.Interaction):
            chosen = sel.values[0]
            del self.parent_view.selected_planes[chosen]
            await inter.response.send_message(f"Ruolo **{chosen}** rimosso.", ephemeral=True)
            await self.parent_view.update_setup_message()

        sel.callback = sel_cb
        view.add_item(sel)
        await interaction.response.send_message("Seleziona il ruolo da rimuovere:", view=view, ephemeral=True)


class ConfirmSetupButton(discord.ui.Button):
    def __init__(self, parent_view: EventSetupView):
        super().__init__(label="Conferma Evento", style=discord.ButtonStyle.success)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if not self.parent_view.selected_planes:
            await interaction.response.send_message("Devi aggiungere almeno un ruolo prima di confermare.", ephemeral=True)
            return

        # Costruzione active_roles: ogni ruolo ha 4 slots e lista utenti vuota
        active_roles = {}
        for role_name, plane_choice in self.parent_view.selected_planes.items():
            active_roles[role_name] = {
                "plane": plane_choice,
                "slots": DEFAULT_SLOTS,
                "users": []
            }

        # Salvataggio persistente
        bookings[self.parent_view.data] = active_roles
        save_bookings()

        # Creiamo la view per le prenotazioni finale (l'utente finale poi sceglierà l'aereo e prenoterà)
        plane_view = PlaneSelectView(self.parent_view.data, self.parent_view.desc, active_roles)
        embed = generate_embed(self.parent_view.data, self.parent_view.desc, active_roles)
        await interaction.response.send_message("Evento creato!", embed=embed, view=plane_view)

# ---------------------------- FINE CREAZIONE EVENTO ----------------------------

# ---------------------------- COMANDO SLASH ----------------------------
@app_commands.command(name="prenotazioni", description="Crea un evento con ruoli dinamici")
@app_commands.describe(
    data="Data della missione (es. 2025-09-22 18:00)",
    desc="Breve descrizione della missione"
)
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    # Creiamo la view dinamica
    setup_view = EventSetupView(data, desc)
    # Inviamo il messaggio iniziale
    msg = await interaction.response.send_message("Configura i ruoli:", view=setup_view, ephemeral=True)
    setup_view.message = msg
# ---------------------------- ON_READY ----------------------------
@# ---------------------------- ON_READY ----------------------------
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    try:
        guild_id = 1358713154116259892  # il tuo server
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
