import discord
from discord import app_commands
from discord.ext import commands
import json
import os

# ---------------------------- CONFIG ----------------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN non trovato — imposta la variabile d'ambiente")
GUILD_ID = 1358713154116259892    # <-- ID del tuo server Discord

# URL immagine di sfondo (pubblicamente accessibile)
BACKGROUND_URL = "https://cdn.discordapp.com/attachments/710523786558046298/1403090934857728001/BCO.png?ex=68c46e43&is=68c31cc3&hm=a2f06f5706910a3ad1e2394b0138f53843d30b4057a4e06087bb102e7cf35b50&"

# Ruoli e capacità massima
roles = {
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
    bookings = {role: [] for role in roles}

def save_bookings():
    with open("prenotazioni.json", "w") as f:
        json.dump(bookings, f)

# ---------------------------- FUNZIONE PER EMBED ----------------------------
def generate_embed(data: str, desc: str, active_roles: list, background_url: str = None):
    embed = discord.Embed(
        title="📋 Prenotazioni Piloti",
        description=f"📅 Missione: {data}\n📝 {desc}",
        color=0x1abc9c
    )
    for role in roles:
        stato = "✅ Attivo" if role in active_roles else "❌ Non Attivo"
        piloti = ", ".join(bookings[role]) if bookings[role] else "Nessuno"
        embed.add_field(
            name=f"{role} ({len(bookings[role])}/{roles[role]['slots']}) - {stato}",
            value=f"Prenotati: {piloti}",
            inline=False
        )
    embed.set_footer(text="Prenota cliccando i pulsanti qui sotto ✈️")

    if background_url:
        embed.set_image(url=background_url)

    return embed

# ---------------------------- BOTTONI ----------------------------
class BookingButton(discord.ui.Button):
    def __init__(self, role, data, desc, active_roles):
        is_active = role in active_roles
        color = discord.ButtonStyle.success if is_active else discord.ButtonStyle.secondary
        super().__init__(label=role, style=color, disabled=not is_active)
        self.role_name = role
        self.data = data
        self.desc = desc
        self.active_roles = active_roles

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name

        # Toggle prenotazione
        if user in bookings[self.role_name]:
            bookings[self.role_name].remove(user)
            save_bookings()
            embed = generate_embed(self.data, self.desc, self.active_roles, background_url=BACKGROUND_URL)
            await interaction.response.edit_message(embed=embed, view=self.view)
            await interaction.followup.send(
                f"❌ Hai rimosso la tua prenotazione da **{self.role_name}**.",
                ephemeral=True
            )
            return

        # Controllo slot disponibili
        if len(bookings[self.role_name]) >= roles[self.role_name]["slots"]:
            await interaction.response.send_message(
                f"⚠️ {self.role_name} è già pieno!",
                ephemeral=True
            )
            return

        # Aggiunta prenotazione
        bookings[self.role_name].append(user)
        save_bookings()
        embed = generate_embed(self.data, self.desc, self.active_roles, background_url=BACKGROUND_URL)
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send(
            f"✅ Prenotazione in **{self.role_name}** confermata!",
            ephemeral=True
        )

# ---------------------------- VIEW ----------------------------
class BookingView(discord.ui.View):
    def __init__(self, data, desc, active_roles):
        super().__init__(timeout=None)
        for role in roles:
            self.add_item(BookingButton(role, data, desc, active_roles))

# ---------------------------- SELECT MENU ----------------------------
class RoleSelect(discord.ui.Select):
    def __init__(self, data, desc):
        options = [discord.SelectOption(label=role, value=role) for role in roles]
        super().__init__(placeholder="Seleziona i ruoli attivi...", min_values=1, max_values=len(roles), options=options)
        self.data = data
        self.desc = desc

    async def callback(self, interaction: discord.Interaction):
        active_roles = self.values
        embed = generate_embed(self.data, self.desc, active_roles, background_url=BACKGROUND_URL)
        view = BookingView(self.data, self.desc, active_roles)
        await interaction.response.edit_message(embed=embed, view=view)

class RoleSelectView(discord.ui.View):
    def __init__(self, data, desc):
        super().__init__()
        self.add_item(RoleSelect(data, desc))

# ---------------------------- COMANDO SLASH ----------------------------
@app_commands.command(name="prenotazioni", description="Mostra i ruoli disponibili per la missione")
@app_commands.describe(
    data="Data della missione (es. 2025-09-12 18:00)",
    desc="Breve descrizione della missione"
)
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    embed = generate_embed(data, desc, active_roles=[], background_url=BACKGROUND_URL)
    view = RoleSelectView(data, desc)
    await interaction.response.send_message(embed=embed, view=view)

# Aggiungo il comando al tree
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