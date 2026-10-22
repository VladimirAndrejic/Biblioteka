# Biblioteka

## Funkcionalnosti
- Prijava bibliotekara i odjava.
- Evidencija knjiga, kategorija i dostupnih primeraka.
- Pretraga knjiga po naslovu, autoru i ISBN-u.
- Evidencija članova i kontakt podataka.
- Izdavanje i vraćanje knjiga, rokovi i status kašnjenja.
- Izveštaji i izvoz pozajmica u CSV.
- Podešavanje naziva i podrazumevanog roka pozajmice.

## Pokretanje na Windows-u
1. Otvorite folder u VS Code-u.
2. Otvorite Terminal > New Terminal.
3. Aktivirajte postojeće virtuelno okruženje: `.\.venv\Scripts\Activate.ps1`
4. Instalirajte zavisnosti: `python -m pip install -r requirements.txt`
5. Pokrenite: `python app.py`
6. Otvorite `http://127.0.0.1:5000`.

## Demo prijava
Korisničko ime: `bibliotekar`
Lozinka: `Biblioteka123!`

Ovo je demo nalog za lokalnu prezentaciju projekta. Za stvarnu upotrebu treba dodati bazu korisnika sa heširanim lozinkama, CSRF zaštitu i bezbedno podešavanje tajnog ključa.

## Postojeća baza
Ako `biblioteka.db` već postoji, aplikacija dodaje nedostajuće kolone i zadržava postojeće knjige, članove i pozajmice.
