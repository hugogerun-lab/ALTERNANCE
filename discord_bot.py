"""
Bot Discord - Alternance BTS GTLA
==================================
Commandes :
  !chercher   → recherche sur France Travail + HelloWork
  !aide       → affiche l'aide

Variables Railway :
  DISCORD_TOKEN
  FRANCE_TRAVAIL_CLIENT_ID
  FRANCE_TRAVAIL_CLIENT_SECRET

Sans Selenium — 100% requests + BeautifulSoup
"""

import os
import asyncio
import logging
import requests
from bs4 import BeautifulSoup

import discord
from discord.ext import commands
from dotenv import load_dotenv

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

KEYWORDS = [
    "BTS GTLA",
    "BTS gestion transports logistique",
    "logistique transport alternance",
]

RYTHME_BLACKLIST = [
    "3 jours école", "3j école", "3 jours en école",
    "4 jours entreprise", "4j entreprise",
    "1 jour école", "1j école",
    "2 jours entreprise", "2j entreprise",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def rythme_acceptable(texte):
    if not texte:
        return True
    texte_lower = texte.lower()
    for mot in RYTHME_BLACKLIST:
        if mot.lower() in texte_lower:
            return False
    return True

# ─── France Travail API ───────────────────────────────────────────────────────

def get_token_france_travail():
    client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "").strip()
    client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        log.warning("France Travail : identifiants manquants.")
        return None
    try:
        resp = requests.post(
            "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "api_offresdemploiv2 o2dsoffre",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as e:
        log.error(f"France Travail token erreur : {e}")
        return None

def scraper_france_travail(keyword):
    annonces = []
    token = get_token_france_travail()
    if not token:
        return annonces
    try:
        resp = requests.get(
            "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
            params={
                "motsCles": keyword,
                "typeContrat": "CJ",
                "range": "0-49",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        for offre in resp.json().get("resultats", []):
            titre = offre.get("intitule", "")
            entreprise = offre.get("entreprise", {}).get("nom", "Non précisé")
            lieu = offre.get("lieuTravail", {}).get("libelle", "Non précisé")
            description = offre.get("description", "")
            job_id = offre.get("id", "")
            job_url = f"https://candidat.francetravail.fr/offres/recherche/detail/{job_id}"

            if not rythme_acceptable(titre + " " + description):
                continue

            annonces.append({
                "titre": titre,
                "entreprise": entreprise,
                "lieu": lieu,
                "url": job_url,
                "plateforme": "France Travail 🏛️"
            })
        log.info(f"France Travail | '{keyword}' → {len(annonces)} annonces")
    except Exception as e:
        log.error(f"France Travail erreur : {e}")
    return annonces

# ─── HelloWork (sans Selenium) ────────────────────────────────────────────────

def scraper_hellowork(keyword):
    annonces = []
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        for page in range(1, 4):
            url = (
                f"https://www.hellowork.com/fr-fr/emploi/recherche.html"
                f"?k={keyword.replace(' ', '+')}"
                f"&c=alternance"
                f"&p={page}"
            )
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                log.warning(f"HelloWork page {page} : status {resp.status_code}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")

            # Chercher les cartes d'annonces
            cartes = soup.select("article, li[data-id-offer], [data-cy='offer-card']")
            if not cartes:
                # Essayer d'autres sélecteurs
                cartes = soup.select(".job-card, .offer-item, .tw-group")

            if not cartes:
                log.warning(f"HelloWork : aucune carte trouvée page {page}")
                break

            log.info(f"HelloWork | '{keyword}' | Page {page} | {len(cartes)} cartes")

            for carte in cartes:
                try:
                    # Titre
                    titre_el = carte.select_one("h2, h3, [data-cy='offer-title'], .offer-title")
                    if not titre_el:
                        continue
                    titre = titre_el.get_text(strip=True)
                    if not titre:
                        continue

                    # Entreprise
                    entreprise_el = carte.select_one(".company-name, .offer-company, [data-cy='company-name']")
                    entreprise = entreprise_el.get_text(strip=True) if entreprise_el else "Non précisé"

                    # Lieu
                    lieu_el = carte.select_one(".offer-location, .location, [data-cy='offer-location']")
                    lieu = lieu_el.get_text(strip=True) if lieu_el else "Non précisé"

                    # URL
                    lien_el = carte.select_one("a[href]")
                    job_url = lien_el["href"] if lien_el else ""
                    if job_url and not job_url.startswith("http"):
                        job_url = "https://www.hellowork.com" + job_url

                    if not rythme_acceptable(titre):
                        continue

                    annonces.append({
                        "titre": titre,
                        "entreprise": entreprise,
                        "lieu": lieu,
                        "url": job_url,
                        "plateforme": "HelloWork 🟢"
                    })

                except Exception as e:
                    log.debug(f"Erreur carte HelloWork : {e}")
                    continue

    except Exception as e:
        log.error(f"HelloWork erreur : {e}")

    return annonces

# ─── Bot Discord ──────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    log.info(f"✅ Bot connecté en tant que {bot.user}")
    print(f"✅ Bot connecté : {bot.user}")

@bot.command(name="aide")
async def aide(ctx):
    embed = discord.Embed(
        title="🎓 Bot Alternance BTS GTLA",
        description="Recherche automatique sur France Travail et HelloWork !",
        color=0x5865F2
    )
    embed.add_field(name="!chercher", value="Lance la recherche d'annonces", inline=False)
    embed.add_field(name="!aide", value="Affiche ce message", inline=False)
    embed.add_field(
        name="Filtres actifs",
        value="✅ BTS GTLA / Gestion Transports Logistique\n✅ Rythme 2j école / 3j entreprise (ou non précisé)\n✅ Contrat alternance uniquement",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(name="chercher")
async def chercher(ctx):
    msg = await ctx.send("🔍 Recherche en cours sur **France Travail** et **HelloWork**...")
    toutes_annonces = []
    loop = asyncio.get_event_loop()

    try:
        # France Travail
        await msg.edit(content="🏛️ Recherche sur **France Travail**...")
        for keyword in KEYWORDS:
            annonces = await loop.run_in_executor(None, scraper_france_travail, keyword)
            toutes_annonces.extend(annonces)

        # HelloWork
        await msg.edit(content="🟢 Recherche sur **HelloWork**...")
        for keyword in KEYWORDS:
            annonces = await loop.run_in_executor(None, scraper_hellowork, keyword)
            toutes_annonces.extend(annonces)

        # Dédoublonner
        vus = set()
        uniques = []
        for a in toutes_annonces:
            cle = (a["titre"].lower(), a["entreprise"].lower())
            if cle not in vus:
                vus.add(cle)
                uniques.append(a)

        await msg.edit(content=f"✅ Terminé ! **{len(uniques)}** annonces trouvées sur France Travail + HelloWork")

        if not uniques:
            await ctx.send("😕 Aucune annonce trouvée. Vérifiez vos identifiants France Travail dans Railway.")
            return

        # Envoyer par blocs de 5
        for i in range(0, min(len(uniques), 25), 5):
            batch = uniques[i:i+5]
            embed = discord.Embed(
                title=f"📋 Annonces {i+1} à {i+len(batch)}",
                color=0x5865F2
            )
            for a in batch:
                embed.add_field(
                    name=f"{a['plateforme']}",
                    value=(
                        f"**{a['titre']}**\n"
                        f"🏢 {a['entreprise']} — 📍 {a['lieu']}\n"
                        f"[Voir l'annonce]({a['url']})"
                    ),
                    inline=False
                )
            await ctx.send(embed=embed)
            await asyncio.sleep(0.5)

    except Exception as e:
        log.error(f"Erreur recherche : {e}", exc_info=True)
        await ctx.send(f"❌ Erreur : `{e}`")

# ─── Lancement ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN manquant !")
    bot.run(token)
