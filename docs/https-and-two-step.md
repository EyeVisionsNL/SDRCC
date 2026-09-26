# HTTPS en tweestapsverificatie — 0.60.0-r1 (develop)

Een optionele beveiligde ingang voor SDRCC via **https://jouw-publieke-IPv4**.
Inloggen gaat met gebruikersnaam/wachtwoord en daarna een zescijferige code uit
je authenticator-app. Geen domeinnaam nodig. Bestaande installaties veranderen
pas van toegang nadat je de setup hieronder uitvoert.

## Eenmalig instellen op de SDRCC-pc

1. Stop de actieve ontvangsttaken in SDRCC. Werk bij vanuit een aparte checkout
   (dit werkt ook als je eerder via de dashboardknop hebt bijgewerkt):

   ```bash
   sdrcc_update_dir="$(mktemp -d)"
   git clone --depth 1 --branch develop https://github.com/EyeVisionsNL/SDRCC.git "$sdrcc_update_dir/SDRCC" &&
   "$sdrcc_update_dir/SDRCC/install.sh"
   ```
2. Stuur in de router **TCP 80 en 443** door naar dezelfde poorten op de SDRCC-pc.
   Verwijder een bestaande forwarding van **8080**. Bij een actieve lokale
   firewall moeten 80 en 443 ook toegelaten zijn. Het publieke adres moet door
   je provider naar jouw router worden gerouteerd (dus geen CGNAT).
3. Voer als gewone SDRCC-gebruiker uit:

   ```bash
   cd ~/SDRCC
   ./install.sh --https-setup
   ```

4. Vul je publieke IPv4 en een e-mailadres voor het certificaat in. Kies je
   gebruikersnaam en een wachtwoord van minimaal 12 tekens. Scan de QR-code
   in je authenticator-app en bevestig de getoonde code.
5. Na succesvolle setup opent SDRCC op `https://jouw-publieke-IP`.
   Test op je mobiel met wifi uit. De setup herstart SDRCC.

De setup installeert nginx, een afzonderlijke Certbot-omgeving (>=5.4), Waitress
voor het beveiligde dashboard en een QR-codebibliotheek. Certbot vraagt een
vertrouwd Let's Encrypt IP-certificaat aan. Deze certificaten zijn ongeveer
zes dagen geldig; de meegeleverde timer controleert tweemaal per dag vernieuwing
(en herlaadt nginx na vernieuwing). **TCP 80 moet daarvoor bereikbaar blijven.**
Op poort 80 wordt alleen de certificaatcontrole aangeboden, geen dashboard.

Op het lokale netwerk gebruik je eveneens HTTPS en dezelfde login. Werkt het
publieke adres intern niet, dan ondersteunt je router mogelijk geen NAT
loopback; mobiele toegang via 4G/5G kan dan wel werken. Een privé-IP in de browser
komt niet overeen met het publieke IP op het certificaat.

## Behoud en herstel

- Wachtwoordhash, authenticatorgeheim en sessies staan uitsluitend in
  `data/security/`, met beperkte bestandsrechten. Ze staan niet in Git of het
  update-manifest. Behandel een backup hiervan als geheim.
- Sessies verlopen na 12 uur. Uitloggen trekt de sessie in; live streams worden
  bij de eerstvolgende controle (bij binnenkomende data) beëindigd.
- Wachtwoord of telefoon kwijt? Voer lokaal opnieuw `./install.sh --https-setup`
  uit. Dat vervangt beide factoren en maakt eerdere sessies ongeldig.
- Publiek IP gewijzigd? Voer dezelfde setup opnieuw uit met het nieuwe adres.
- Certificaataanvraag mislukt? Controleer poort 80/CGNAT en voer de setup opnieuw
  uit. De eerste voorbereiding publiceert nooit een onbeveiligde backend.
- Na activering luistert poort 8080 uitsluitend op loopback. Ontbrekende of
  onleesbare beveiligingsconfiguratie stopt de service; zij valt niet terug op
  onbeveiligde toegang. Verwijder de configuratie dus niet om een login te resetten.
- De updateknop blijft werken. De lokale updater ziet uitsluitend een minimale
  statusrespons zonder stationinformatie; externe API-verzoeken vereisen login.
- Andere webdiensten, zoals rechtstreeks geopende AIS-catcher/readsb-kaarten op
  eigen poorten, krijgen hiermee geen SDRCC-login. Deze setup publiceert alleen
  SDRCC. Bestaande externe kaart-URLs worden niet herschreven.
- Verwijderen van SDRCC verwijdert de eigen nginx-site en vernieuwingstimer, maar
  laat nginx en de Certbot-omgeving/certificaatarchieven staan voor beheer.

Controles op de pc:

```bash
systemctl status sdrcc.service nginx.service sdrcc-cert-renew.timer --no-pager
sudo /opt/sdrcc-certbot/bin/certbot certificates
sudo /opt/sdrcc-certbot/bin/certbot renew --cert-name sdrcc-ip --dry-run
```

## Validatie

`venv/bin/python scripts/validate_web_security.py` test onder andere de twee
factoren, CSRF, cookies, persistente blokkering van herhaalde pogingen, codehergebruik,
sessieverval en de lokale updatecontrole. Browser-fetch-tests controleren ook
bestandsuploads en het niet doorsturen van tokens naar andere websites.
Certificaatuitgifte, router-forwarding en daadwerkelijke systemd-herstarts
moeten op de ontvanger worden getest; hiervoor zijn het echte IP en lokale
beheerdersrechten nodig.

Bron voor het IP-certificaatpad:
https://letsencrypt.org/2026/03/11/shorter-certs-certbot
