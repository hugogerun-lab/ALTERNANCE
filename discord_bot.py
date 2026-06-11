"""
Bot Discord - Alternance BTS GTLA
==================================
Commandes disponibles :
  !chercher   → lance la recherche sur France Travail + HelloWork
  !aide       → affiche l'aide

Variables d'environnement requises :
  DISCORD_TOKEN=votre_token_discord
  FRANCE_TRAVAIL_CLIENT_ID=votre_client_id
  FRANCE_TRAVAIL_CLIENT_SECRET=votre_client_secret
  HELLOWORK_EMAIL=votre@email.com
  HELLOWORK_PASSWORD=votre_mot_de_passe

France Travail : API officielle gratuite (remplace Indeed)
HelloWork : connexion + mise en favoris automatique
"""

import os
import time
import random
import asyncio
import logging
import requests

import discord
from discord.ext import commands
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

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

# ─── Helpers ──────────────────────────────────────────────────────────────────

def pause(mini=1.5, maxi=3.5):
    time.sleep(random.uniform(mini, maxi))

def rythme_acceptable(texte):
    if not texte:
        return True
    texte_lower = texte.lower()
    for mot in RYTHME_BLACKLIST:
        if mot.lower() in texte_lower:
            return False
    return True

def creer_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # Utiliser Chrome/Chromium installé par le système (Railway/Nix)
    chrome_bin = os.getenv("CHROME_BIN", "")
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH", "")
    if chrome_bin:
        options.binary_location = chrome_bin
    if chromedriver_path:
        service = Service(chromedriver_path)
    else:
        service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

# ─── France Travail API ───────────────────────────────────────────────────────

def get_token_france_travail():
    """Récupère un token OAuth2 pour l'API France Travail."""
    client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "")
    client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.warning("France Travail : identifiants manquants.")
        return None
    try:
        resp = requests.post(
            "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
            "?realm=%2Fpartenaire",
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
    """Recherche des offres via l'API France Travail."""
    annonces = []
    token = get_token_france_travail()
    if not token:
        log.warning("France Travail : token indisponible, recherche ignorée.")
        return annonces

    try:
        params = {
            "motsCles": keyword,
            "typeContrat": "CJ",   # CJ = contrat d'apprentissage / alternance
            "range": "0-49",
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        resp = requests.get(
            "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
            params=params,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        offres = data.get("resultats", [])

        for offre in offres:
            titre = offre.get("intitule", "")
            entreprise = offre.get("entreprise", {}).get("nom", "Non précisé")
            lieu = offre.get("lieuTravail", {}).get("libelle", "Non précisé")
            job_url = offre.get("origineOffre", {}).get("urlOrigine", "")
            description = offre.get("description", "")

            # Filtrer rythme
            if not rythme_acceptable(titre + " " + description):
                continue

            annonces.append({
                "titre": titre,
                "entreprise": entreprise,
                "lieu": lieu,
                "url": job_url or f"https://candidat.francetravail.fr/offres/recherche/detail/{offre.get('id', '')}",
                "favori": False,
                "plateforme": "France Travail"
            })

        log.info(f"France Travail | '{keyword}' → {len(annonces)} annonces")

    except Exception as e:
        log.error(f"France Travail erreur : {e}")

    return annonces

# ─── HelloWork ────────────────────────────────────────────────────────────────

def scraper_hellowork(keyword):
    annonces = []
    driver = creer_driver()
    wait = WebDriverWait(driver, 15)

    try:
        # Connexion HelloWork
        email = os.getenv("HELLOWORK_EMAIL", "")
        password = os.getenv("HELLOWORK_PASSWORD", "")
        if email and password:
            try:
                driver.get("https://www.hellowork.com/fr-fr/compte/connexion.html")
                pause()
                # Accepter cookies
                try:
                    driver.find_element(
                        By.XPATH, "//button[contains(text(),'Accepter')]"
                    ).click()
                    pause(1, 2)
                except NoSuchElementException:
                    pass
                champ = wait.until(EC.presence_of_element_located((By.ID, "email")))
                champ.send_keys(email)
                driver.find_element(By.ID, "password").send_keys(password)
                driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
                pause(2, 4)
                log.info("HelloWork : connexion réussie ✅")
            except Exception as e:
                log.warning(f"HelloWork connexion échouée : {e}")

        url = (
            f"https://www.hellowork.com/fr-fr/emploi/recherche.html"
            f"?k={keyword.replace(' ', '+')}&c=alternance"
        )
        driver.get(url)
        pause()

        # Accepter cookies si pas encore fait
        try:
            driver.find_element(
                By.XPATH, "//button[contains(text(),'Accepter')]"
            ).click()
            pause(1, 2)
        except NoSuchElementException:
            pass

        for page in range(3):
            try:
                cartes = wait.until(
                    EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, "article.offer-card, li[data-id-offer], [data-cy='offer-card']")
                    )
                )
            except TimeoutException:
                log.warning(f"HelloWork : aucune annonce page {page+1}")
                break

            log.info(f"HelloWork | '{keyword}' | Page {page+1} | {len(cartes)} cartes")

            for carte in cartes:
                try:
                    titre = carte.find_element(
                        By.CSS_SELECTOR, "h2, h3, [data-cy='offer-title'], .offer-title"
                    ).text.strip()
                    entreprise = ""
                    lieu = ""
                    try:
                        entreprise = carte.find_element(
                            By.CSS_SELECTOR, ".company-name, .offer-company, [data-cy='company-name']"
                        ).text.strip()
                    except NoSuchElementException:
                        pass
                    try:
                        lieu = carte.find_element(
                            By.CSS_SELECTOR, ".offer-location, .location, [data-cy='offer-location']"
                        ).text.strip()
                    except NoSuchElementException:
                        pass

                    if not rythme_acceptable(titre):
                        continue

                    lien = carte.find_element(By.CSS_SELECTOR, "a")
                    job_url = lien.get_attribute("href")
                    if not job_url.startswith("http"):
                        job_url = "https://www.hellowork.com" + job_url

                    # Ouvrir l'annonce dans un nouvel onglet
                    driver.execute_script("window.open(arguments[0]);", job_url)
                    driver.switch_to.window(driver.window_handles[-1])
                    pause(1.5, 3)

                    # Vérifier description
                    try:
                        description = wait.until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR,
                                 ".offer-description, #job-description, "
                                 ".job-description, [data-cy='offer-description']")
                            )
                        ).text
                        if not rythme_acceptable(description):
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                            continue
                    except TimeoutException:
                        pass

                    # Mettre en favori
                    favori = False
                    try:
                        btn = wait.until(EC.element_to_be_clickable(
                            (By.CSS_SELECTOR,
                             "button[aria-label*='favori'], button[aria-label*='Favori'], "
                             ".bookmark-btn, .save-offer, [data-cy='bookmark-btn']")
                        ))
                        driver.execute_script("arguments[0].click();", btn)
                        favori = True
                        pause(0.5, 1)
                        log.info(f"  ⭐ Favori ajouté : {titre}")
                    except (TimeoutException, NoSuchElementException):
                        log.debug(f"  ➡️ Pas de bouton favori pour : {titre}")

                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                    annonces.append({
                        "titre": titre,
                        "entreprise": entreprise,
                        "lieu": lieu,
                        "url": job_url,
                        "favori": favori,
                        "plateforme": "HelloWork"
                    })

                except Exception as e:
                    log.debug(f"Erreur carte HelloWork : {e}")
                    try:
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                    except Exception:
                        pass
                    continue

            # Page suivante
            try:
                btn_next = driver.find_element(
                    By.CSS_SELECTOR, "a[rel='next'], a.pagination-next, [data-cy='pagination-next']"
                )
                btn_next.click()
                pause(2, 4)
            except NoSuchElementException:
                log.info("HelloWork : dernière page atteinte.")
                break

    finally:
        driver.quit()

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
        description="Je cherche automatiquement des annonces d'alternance sur France Travail et HelloWork !",
        color=0x5865F2
    )
    embed.add_field(name="!chercher", value="Lance la recherche sur France Travail + HelloWork", inline=False)
    embed.add_field(name="!aide", value="Affiche ce message", inline=False)
    embed.add_field(
        name="Filtres actifs",
        value="✅ BTS GTLA / Gestion Transports Logistique\n✅ Rythme 2j école / 3j entreprise (ou non précisé)\n✅ Contrat d'alternance uniquement",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(name="chercher")
async def chercher(ctx):
    msg = await ctx.send("🔍 Lancement de la recherche sur **France Travail** et **HelloWork**...")
    toutes_annonces = []
    loop = asyncio.get_event_loop()

    try:
        # ── France Travail (API) ──
        await msg.edit(content="🏛️ Recherche sur **France Travail** (API officielle)...")
        for keyword in KEYWORDS:
            annonces = await loop.run_in_executor(None, scraper_france_travail, keyword)
            toutes_annonces.extend(annonces)

        # ── HelloWork (Selenium) ──
        await msg.edit(content="🔍 Recherche sur **HelloWork** (connexion + favoris)...")
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

        favoris = sum(1 for a in uniques if a["favori"])
        await msg.edit(
            content=f"✅ Terminé ! **{len(uniques)}** annonces trouvées "
                    f"(**{favoris}** mis en favoris sur HelloWork)"
        )

        if not uniques:
            await ctx.send("😕 Aucune annonce trouvée pour vos critères.")
            return

        # Envoyer les résultats par blocs de 5
        for i in range(0, min(len(uniques), 25), 5):
            batch = uniques[i:i+5]
            couleur = 0x5865F2 if batch[0]["plateforme"] == "France Travail" else 0x00b300
            embed = discord.Embed(
                title=f"📋 Annonces {i+1} à {i+len(batch)}",
                color=couleur
            )
            for a in batch:
                if a["plateforme"] == "HelloWork":
                    statut = "⭐ Favori" if a["favori"] else "🟢 HelloWork"
                else:
                    statut = "🏛️ France Travail"
                embed.add_field(
                    name=f"{statut} | {a['plateforme']}",
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
        raise ValueError("DISCORD_TOKEN manquant dans .env !")
    bot.run(token)
