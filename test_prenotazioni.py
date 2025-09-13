import discord
from discord import app_commands
from discord.ext import commands
import json
import os

# ---------------------------- CONFIG ----------------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN non trovato — imposta la variabile d'ambiente")
GUILD_ID = 1358713154116259892  # ID del server Discord

BACKGROUND_URL = "https://cdn.discordapp.com/attachments/710523786558046298/1403090934857728001/BCO.png"

# Ruoli di default (slots)
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

# ---------------------------- BOTTONI PRENOTAZIONI ----------------------------
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

        # Controllo globale: l'utente è già in un altro ruolo?
        already_in_role = None
        for r, info in self.active_roles.items():
            if user in info["users"]:
                already_in_role = r
                break

        if already_in_role and already_in_role != self.role_name:
            await interaction.response.send_message(
                f"⚠️ Sei già prenotato in **{already_in_role}**! "
                f"Devi prima cancellarti da quel ruolo prima di prenotarti qui.",
                ephemeral=True
            )
            return

        role_info = self.active_roles[self.role_name]

        # Se l'utente era già nel ruolo selezionato => rimuovi
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

        # Controllo slot pieno
        if len(role_info["users"]) >= role_info["slots"]:
            await interaction.response.send_message(
                f"⚠️ {self.role_name} è già pieno!",
                ephemeral=True
            )
            return

        # Aggiungi utente
        role_info["users"].append(user)
        save_bookings()
        embed = generate_embed(self.data, self.desc, self.active_roles)
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send(
            f"✅ Prenotazione in **{self.role_name}** confermata!",
            ephemeral=True
        )


# ---------------------------- VIEW PRENOTAZIONI ----------------------------
class BookingView(discord.ui.View):
    def __init__(self, data, desc, active_roles, plane):
        super().__init__(timeout=None)
        for role in active_roles:
            self.add_item(BookingButton(role, data, desc, active_roles, plane))

# ---------------------------- SELECT MENU PILOTI ----------------------------
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
        # Mostra tutti i ruoli nell'embed, ma abilita solo i pulsanti dei ruoli compatibili
        embed = generate_embed(self.data, self.desc, self.active_roles)
        view = BookingView(self.data, self.desc, self.active_roles, chosen_plane)
        await interaction.response.edit_message(embed=embed, view=view)

class PlaneSelectView(discord.ui.View):
    def __init__(self, data, desc, active_roles):
        super().__init__()
        self.add_item(PlaneSelect(data, desc, active_roles))

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
        await interaction.response.send_message(
            f"Aereo per {self.role} impostato su {self.values[0]}", ephemeral=True
        )

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
        plane_view = PlaneSelectView(self.parent_view.data, self.parent_view.desc, active_roles)
        embed = generate_embed(self.parent_view.data, self.parent_view.desc, active_roles)
        await interaction.response.send_message(embed=embed, view=plane_view)

# ---------------------------- COMANDO SLASH ----------------------------
@app_commands.command(name="prenotazioni", description="Crea un evento con ruoli e aerei")
@app_commands.describe(
    data="Data della missione (es. 2025-09-12 18:00)",
    desc="Breve descrizione della missione"
)
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup_view = EventSetupView(roles_template.keys(), data, desc)
    for view in setup_view.role_views:
        await interaction.response.send_message("Seleziona aerei per i ruoli:", view=view, ephemeral=True)
    await interaction.followup.send("Conferma l'evento quando hai completato la scelta degli aerei:", view=setup_view.confirm_view, ephemeral=True)

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

# ---------------------------- AVVIO BOT ----------------------------
bot.run(TOKEN)
