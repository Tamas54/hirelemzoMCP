# RSSHub Twitter cookie renewal

A `TWITTER_AUTH_TOKEN` Railway env-var az `x.com` session-cookie értéke
a `Clauscommandant` throwaway X-fiókra. **Az X ~1-2 hetente új cookie-ra
rotálja**, ekkor az `rsshub-production-82fc.up.railway.app/twitter/...`
HTTP 503-zal vagy `ConfigNotFoundError`-rel kezd el válaszolni.

## Mikor látod, hogy megújítás kell

- Az `echolot_health` tool top-active sources-listájáról eltűnnek az X-fiókok
- A `fetch_log`-ban `HTTP 503` jelenik meg a `rsshub-production-82fc` URL-eket
  célzó request-eknél
- Manuál teszt: `curl https://rsshub-production-82fc.up.railway.app/twitter/user/ISW`
  → 503 + "Twitter cookie ... is not valid" vagy "ConfigNotFoundError"

## Renewal lépéssor (5 perc)

### 1. Új cookie kinyerése a böngészőből

1. Brave / Chrome: nyisd meg **<https://x.com>**-ot bejelentkezve a
   `Clauscommandant` fiókkal (email: `csizidr2005@gmail.com`)
2. **F12** → DevTools nyitva
3. Menj az **`Application`** tab-ra (magyar UI-ban "Alkalmazás" — ha a
   tab-sávban nem látszik, kattints a `>>` legördülőre a Network mellett)
4. Bal panel: **`Storage`** → **`Cookies`** → kattints `https://x.com`-ra
5. A táblázatban keresd meg az **`auth_token`** nevű sort
6. **Dupla-kattintás a Value oszlopra** → kijelöli a teljes ~40-karakteres
   hex-stringet → **Ctrl+C**

### 2. Cookie behelyezése Railway-be

1. <https://railway.app> → rsshub project → **rsshub service**
2. **Variables** tab
3. Keresd meg a `TWITTER_AUTH_TOKEN` sort → kattints a Value-mezőre →
   töröld a régi értéket → illesztsd be az új cookie-t
4. Mentés → a Railway automatikusan re-deploy-ol (~30-60 mp)

### 3. Smoke-teszt

```bash
RSSHUB="https://rsshub-production-82fc.up.railway.app"
curl -s -m 30 "$RSSHUB/twitter/user/ISW" | grep -c "<item>"
```

Ha `>= 5` → siker, X-források visszaálltak.
Ha `0` vagy 503 → vissza a böngészőhöz, esetleg login-state romlott meg
(unfollow a captcha-t, MFA-prompt-ot, gyanús-activity-figyelmeztetést).

## Konzol-trükk, ha az Application tab nem elérhető

A `document.cookie`-on **nem** látszik az `auth_token`, mert HttpOnly
flaggel van állítva. A Console-ban semmilyen JS-szel nem éred el.
**KÖTELEZŐ az Application/Storage tab-on át.**

## Miért nem username/password?

Az RSSHub 2026-os verziójában `lib/config.ts`-ben:

```typescript
// username: envs.TWITTER_USERNAME?.split(','),    // KIKOMMENTELVE
// password: envs.TWITTER_PASSWORD?.split(','),    // KIKOMMENTELVE
authToken: envs.TWITTER_AUTH_TOKEN?.split(','),    // EZ AZ EGYETLEN ÚT
```

Az `TWITTER_USERNAME` + `TWITTER_PASSWORD` env-varokat figyelmen kívül
hagyja. Csak az `auth_token` cookie működik. Ezt a designt etikai/TOS
okokból cserélték — automatizált bejelentkezés bot-szerű session-okat
generál, ami az X szabályait sérti.

## Automatizálási TODO (későbbi)

- **Playwright-cron**: egy különálló Railway service, ami minden 7. nap
  bejelentkezik a Clauscommandant fiókba (saved-credential-szel a
  service env-vars-ben), megszerzi az új `auth_token`-t, és Railway-API-n
  átírja az rsshub service `TWITTER_AUTH_TOKEN` env-vart automatikusan
- Egyszerűbb fallback: a `echolot_health` tool jelzze, ha az X-sphere-ek
  cikkszáma 24h alatt 0-ra esik — push-üzenet (Telegram) a Kommandantnak,
  hogy itt az ideje a manuál renewalnek

Egyelőre ezek nincsenek implementálva — manuál renewal 1-2 hetente.

## Memória-hivatkozások

- `feedback_credentials_never_in_repo.md` — credentials sose git-be
- `feedback_own_to_own_deploy.md` — RSSHub fork-ból deploy
- `brave_mcp_og_fastpath_todo.md` — kapcsolódó infrastruktúra-doksi
