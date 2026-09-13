from flask import Flask, render_template, request, send_file
import csv
import math
import json
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)


def profilok_beolvasasa():
    profilok = {}
    

    with open("profiles.csv", newline="", encoding="utf-8-sig") as fajl:
        olvaso = csv.DictReader(fajl)

        for sor in olvaso:
            csalad = sor["family"]
            nev = sor["name"]

            if csalad not in profilok:
                profilok[csalad] = {}

            profilok[csalad][nev] = {
                "h": float(sor["h_mm"]),
                "b": float(sor["b_mm"]),
                "tw": float(sor["tw_mm"]),
                "tf": float(sor["tf_mm"]),
                "r": float(sor["r1_mm"]),
                "A": float(sor["A_cm2"]),
                "Iy": float(sor["Iy_cm4"]),
                "Iz": float(sor["Iz_cm4"]),
                "Wel_y": float(sor["Wely_cm3"]),
                "Wpl_y": float(sor["Wply_cm3"]),
                "Wel_z": float(sor["Welz_cm3"]),
                "Wpl_z": float(sor["Wplz_cm3"]),
                "Av_z": float(sor["Avz_cm2"])
            }

    return profilok

ACELMINOSEGEK = {
    "S235": 235.0,
    "S275": 275.0,
    "S355": 355.0
}


SECTIONS = profilok_beolvasasa()


@app.route("/")
def index():

    csalad = request.args.get("csalad", "HEA")

    if csalad not in SECTIONS:
        csalad = "HEA"

    szelvenyek = SECTIONS[csalad]

    szelveny_nev = request.args.get(
        "szelveny",
        list(szelvenyek.keys())[0]
    )

    if szelveny_nev not in szelvenyek:
        szelveny_nev = list(szelvenyek.keys())[0]

    szelveny = szelvenyek[szelveny_nev]
    anyag = request.args.get("anyag", "S235")
    fy = ACELMINOSEGEK.get(anyag, 235.0)

    epsilon = math.sqrt(235 / fy)

    c_flange = (
     szelveny["b"]
     - szelveny["tw"]
     - 2 * szelveny["r"]
    ) / 2

    lambda_flange = c_flange / szelveny["tf"]

    if lambda_flange <= 9 * epsilon:
        flange_class = 1
    elif lambda_flange <= 10 * epsilon:
        flange_class = 2
    elif lambda_flange <= 14 * epsilon:
     flange_class = 3
    else:
     flange_class = 4

    c_web = (
        szelveny["h"]
        - 2 * szelveny["tf"]
        - 2 * szelveny["r"]
    )

    lambda_web = c_web / szelveny["tw"]

    gamma_M0 = 1.0


    NEd = request.args.get("NEd", "0")
    VyEd = request.args.get("VyEd", "0")
    VzEd = request.args.get("VzEd", "0")
    MyEd = request.args.get("MyEd", "0")
    MzEd = request.args.get("MzEd", "0")
    TEd = request.args.get("TEd", "0")

    def szamma(ertek):
        try:
            return float(ertek)
        except (ValueError, TypeError):
            return 0.0

    NEd = szamma(NEd)
    VyEd = szamma(VyEd)
    VzEd = szamma(VzEd)
    MyEd = szamma(MyEd)
    MzEd = szamma(MzEd)
    TEd = szamma(TEd)

    # EC3 osztályozásnál a nyomó normálerőt pozitív értékkel kezeljük
    N_compression = max(-NEd, 0.0)

    # kN -> N
    N_compression_N = N_compression * 1000

    # Gerinc nyomott hányada Class 1-2 vizsgálathoz
    alpha = 0.5 * (
      1
      + N_compression_N
      / (c_web * szelveny["tw"] * fy)
    )

    # alpha legfeljebb 1.0
    alpha = min(alpha, 1.0)

    # Gerinc osztályozása - Class 1 és Class 2

    if alpha <= 0.5:
        web_limit_class1 = 36 * epsilon / alpha
        web_limit_class2 = 41.5 * epsilon / alpha
    else:
        web_limit_class1 = 396 * epsilon / (13 * alpha - 1)
        web_limit_class2 = 456 * epsilon / (13 * alpha - 1)

    if lambda_web <= web_limit_class1:
        web_class = 1
    elif lambda_web <= web_limit_class2:
        web_class = 2
    else:
        web_class = 3

    # --- Gerinc feszültségeloszlása a Class 3 / 4 vizsgálathoz ---

    A_mm2 = szelveny["A"] * 100
    Iy_mm4 = szelveny["Iy"] * 10000

    # A gerinc sík részének felső és alsó széle a súlyponttól
    y_web = c_web / 2

    # Normálerőből származó feszültség
    # A programban NEd < 0 = nyomás
    sigma_N = NEd * 1000 / A_mm2

    # MyEd: kNm -> Nmm
    MyEd_Nmm = MyEd * 1_000_000

    # Hajlításból származó feszültség a gerinc két szélén
    sigma_M = MyEd_Nmm * y_web / Iy_mm4

    sigma_top = sigma_N - sigma_M
    sigma_bottom = sigma_N + sigma_M

    # --- Psi meghatározása a gerinc Class 3 / 4 vizsgálatához ---

    sigma_1 = min(sigma_top, sigma_bottom)
    sigma_2 = max(sigma_top, sigma_bottom)

    if sigma_1 < 0:
        # A legnagyobb nyomófeszültséghez viszonyítunk
        if abs(sigma_1) > 1e-9:
            psi = sigma_2 / sigma_1
        else:
            psi = 1.0
    else:
            # Nincs nyomott gerincrész
            psi = 1.0

    if psi > -1:
        web_limit_class3 = 42 * epsilon / (0.67 + 0.33 * psi)
    else:
        web_limit_class3 = 62 * epsilon * (1 - psi) * math.sqrt(-psi)
    if web_class == 3:
        if lambda_web <= web_limit_class3:
            web_class = 3
        else:
            web_class = 4

        print("lambda_flange =", lambda_flange)
        print("flange_class =", flange_class)
        print("lambda_web =", lambda_web)
        print("alpha =", alpha)
        print("web_limit_class1 =", web_limit_class1)
        print("web_limit_class2 =", web_limit_class2)
        print("psi =", psi)
        print("web_limit_class3 =", web_limit_class3)
        print("web_class =", web_class)

    section_class = max(flange_class, web_class)
    print("TESZT OSZTALY:", section_class, "WEB:", web_class, "LAMBDA:", lambda_web)
    print("CLASS1 HATAR:", web_limit_class1)
    print("CLASS2 HATAR:", web_limit_class2)
    print("CLASS3 HATAR:", web_limit_class3)
    print("ALPHA:", alpha)
    print("PSI:", psi)

    eredmeny = None

    if request.args.get("szamitas") == "1":

        # --- NORMÁLERŐ ELLENÁLLÁS ---

        A_mm2 = szelveny["A"] * 100

        Nc_Rd = A_mm2 * fy / gamma_M0 / 1000
        Nt_Rd = A_mm2 * fy / gamma_M0 / 1000

        if NEd < 0:
            N_Rd = Nc_Rd
            N_tipus = "nyomas"
        elif NEd > 0:
            N_Rd = Nt_Rd
            N_tipus = "huzas"
        else:
            N_Rd = Nc_Rd
            N_tipus = None

        kihasznaltsag_N = abs(NEd) / N_Rd

        # --- NYÍRÁSI ELLENÁLLÁS Vz ---

        Av_z_mm2 = szelveny["Av_z"] * 100

        Vz_Rd = Av_z_mm2 * fy / math.sqrt(3) / gamma_M0 / 1000

        kihasznaltsag_Vz = abs(VzEd) / Vz_Rd
        # --- NAGY NYÍRÓERŐ Vz ---
        rho_Vz = 0.0

        if abs(VzEd) > 0.5 * Vz_Rd:
            rho_Vz = (2 * abs(VzEd) / Vz_Rd - 1) ** 2
        else:
            rho_Vz = 0.0

        # --- HAJLÍTÁSI ELLENÁLLÁS Y-Y ---

        if section_class <= 2:
            Wpl_y_mm3 = szelveny["Wpl_y"] * 1000

            if rho_Vz > 0:
                Aw_mm2 = (szelveny["h"] - 2 * szelveny["tf"]) * szelveny["tw"]

                Wy_mm3 = (
                    Wpl_y_mm3
                    - rho_Vz * Aw_mm2**2 / (4 * szelveny["tw"])
                )

                Wy_mm3 = min(Wy_mm3, Wpl_y_mm3)
            else:
                Wy_mm3 = Wpl_y_mm3

        elif section_class == 3:
            Wy_mm3 = szelveny["Wel_y"] * 1000

        else:
            Wy_mm3 = None

        if Wy_mm3 is not None:
            My_Rd = Wy_mm3 * fy / gamma_M0 / 1_000_000
            kihasznaltsag_My = abs(MyEd) / My_Rd
        else:
            My_Rd = None
            kihasznaltsag_My = None

        # --- NYÍRÁSI ELLENÁLLÁS Vy ---

        Av_y_mm2 = 2 * szelveny["b"] * szelveny["tf"]

        Vy_Rd = Av_y_mm2 * fy / math.sqrt(3) / gamma_M0 / 1000

        kihasznaltsag_Vy = abs(VyEd) / Vy_Rd

        if abs(VyEd) > 0.5 * Vy_Rd:
            rho_Vy = (2 * abs(VyEd) / Vy_Rd - 1) ** 2
        else:
            rho_Vy = 0.0


        # --- HAJLÍTÁSI ELLENÁLLÁS Z-Z ---

        if section_class <= 2:
            Wz_mm3 = szelveny["Wpl_z"] * 1000
        elif section_class == 3:
            Wz_mm3 = szelveny["Wel_z"] * 1000
        else:
            Wz_mm3 = None

        if Wz_mm3 is not None:
            Mz_Rd = Wz_mm3 * fy / gamma_M0 / 1_000_000
            kihasznaltsag_Mz = abs(MzEd) / Mz_Rd
        else:
            Mz_Rd = None
            kihasznaltsag_Mz = None



        # --- NORMÁLERŐ + KÉTTENGELYŰ HAJLÍTÁS ---

        if My_Rd is not None and Mz_Rd is not None:
            kihasznaltsag_NMM = (
                abs(NEd) / Nc_Rd
                + abs(MyEd) / My_Rd
                + abs(MzEd) / Mz_Rd
            )
        else:
            kihasznaltsag_NMM = None

        # --- NORMÁLERŐ + HAJLÍTÁS + NAGY NYÍRÁS ---
        # Konzervatív burkoló Alex programja szerint

        kihasznaltsag_NMMV = None
        N_Rd_red = None
        My_Rd_red = None
        Mz_Rd_red = None

        if section_class <= 2 and (rho_Vz > 0 or rho_Vy > 0):
            rho_max = max(rho_Vy, rho_Vz)
            redukcios_tenyezo = 1.0 - rho_max

            # Eredeti, nyírással még nem redukált hajlítási ellenállások
            My_Rd_alap = (
                szelveny["Wpl_y"] * 1000 * fy / gamma_M0 / 1_000_000
            )

            Mz_Rd_alap = (
                szelveny["Wpl_z"] * 1000 * fy / gamma_M0 / 1_000_000
            )

            N_Rd_red = Nc_Rd * redukcios_tenyezo
            My_Rd_red = My_Rd_alap * redukcios_tenyezo
            Mz_Rd_red = Mz_Rd_alap * redukcios_tenyezo

            kihasznaltsag_NMMV = (
                abs(NEd) / N_Rd_red
                + abs(MyEd) / My_Rd_red
                + abs(MzEd) / Mz_Rd_red
        )

        # --- CSAVARÁS ---

        csavaras_figyelmeztetes = None

        if abs(TEd) > 0:
            csavaras_figyelmeztetes = (
             "Csavarónyomaték van megadva. "
                "Nyitott I/H szelvény esetén a csavarási és vetemedési "
                "ellenőrzéshez további adatok / VEM vizsgálat szükséges."
    )

        # --- EREDMÉNYEK ---
        # --- ÖSSZESÍTETT EREDMÉNY ---
        kihasznaltsagok = [
            kihasznaltsag_N,
            kihasznaltsag_My,
            kihasznaltsag_Mz,
            kihasznaltsag_Vz,
            kihasznaltsag_Vy,
            kihasznaltsag_NMM,
            kihasznaltsag_NMMV,
        ]

        kihasznaltsagok = [x for x in kihasznaltsagok if x is not None]

        max_kihasznaltsag = max(kihasznaltsagok) if kihasznaltsagok else 0
        ossz_megfelel = max_kihasznaltsag <= 1.0

        eredmeny = {
            "Nc_Rd": Nc_Rd,
            "Nt_Rd": Nt_Rd,
            "N_Rd": N_Rd,
            "N_tipus": N_tipus,
            "kihasznaltsag": kihasznaltsag_N,
            "szazalek": kihasznaltsag_N * 100,
            "megfelel": kihasznaltsag_N <= 1.0,

            "My_Rd": My_Rd,
            "kihasznaltsag_My": kihasznaltsag_My,
            "szazalek_My": kihasznaltsag_My * 100 if kihasznaltsag_My is not None else None,
            "megfelel_My": kihasznaltsag_My <= 1.0 if kihasznaltsag_My is not None else None,

            "Mz_Rd": Mz_Rd,
            "kihasznaltsag_Mz": kihasznaltsag_Mz,
            "szazalek_Mz": kihasznaltsag_Mz * 100 if kihasznaltsag_Mz is not None else None,
            "megfelel_Mz": kihasznaltsag_Mz <= 1.0 if kihasznaltsag_Mz is not None else None,

            "NMM_kihasznaltsag": kihasznaltsag_NMM,
            "NMM_szazalek": kihasznaltsag_NMM * 100 if kihasznaltsag_NMM is not None else None,
            "NMM_megfelel": kihasznaltsag_NMM <= 1.0 if kihasznaltsag_NMM is not None else None,
            "NMMV_kihasznaltsag": kihasznaltsag_NMMV,
            "NMMV_szazalek": kihasznaltsag_NMMV * 100 if kihasznaltsag_NMMV is not None else None,
            "NMMV_megfelel": kihasznaltsag_NMMV <= 1.0 if kihasznaltsag_NMMV is not None else None,

            "N_Rd_red": N_Rd_red,
            "My_Rd_red": My_Rd_red,
            "Mz_Rd_red": Mz_Rd_red,
            

            "Vz_Rd": Vz_Rd,
            "kihasznaltsag_Vz": kihasznaltsag_Vz,
            "szazalek_Vz": kihasznaltsag_Vz * 100,
            "megfelel_Vz": kihasznaltsag_Vz <= 1.0,

            "Vy_Rd": Vy_Rd,
            "kihasznaltsag_Vy": kihasznaltsag_Vy,
            "szazalek_Vy": kihasznaltsag_Vy * 100,
            "megfelel_Vy": kihasznaltsag_Vy <= 1.0,

            "TEd": TEd,
            "csavaras_figyelmeztetes": csavaras_figyelmeztetes,

            "flange_class": flange_class,
            "web_class": web_class,
            "section_class": section_class,

            "max_kihasznaltsag": max_kihasznaltsag,
            "max_szazalek": max_kihasznaltsag * 100,
            "ossz_megfelel": ossz_megfelel,
    }

    return render_template(
        "index.html",
        csalad=csalad,
        csaladok=SECTIONS.keys(),
        szelveny_nev=szelveny_nev,
        szelvenyek=szelvenyek,
        szelveny=szelveny,
        anyag=anyag,

        NEd=NEd,
        VyEd=VyEd,
        VzEd=VzEd,
        MyEd=MyEd,
        MzEd=MzEd,
        TEd=TEd,

        eredmeny=eredmeny
)
@app.route("/pdf")
def pdf_export():
    csalad = request.args.get("csalad", "IPE")
    szelveny_nev = request.args.get("szelveny", "IPE 200")
    anyag = request.args.get("anyag", "S235")
    eredmenyek_json = request.args.get("eredmenyek", "[]")

    try:
        eredmeny_sorok = json.loads(eredmenyek_json)
    except json.JSONDecodeError:
        eredmeny_sorok = []

    NEd = float(request.args.get("NEd", 0) or 0)
    VyEd = float(request.args.get("VyEd", 0) or 0)
    VzEd = float(request.args.get("VzEd", 0) or 0)
    MyEd = float(request.args.get("MyEd", 0) or 0)
    MzEd = float(request.args.get("MzEd", 0) or 0)
    TEd = float(request.args.get("TEd", 0) or 0)

    szelveny = SECTIONS[csalad][szelveny_nev]
    fy = ACELMINOSEGEK[anyag]
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="Acél keresztmetszet ellenőrző - EC3"
    )

    styles = getSampleStyleSheet()

    tartalom = [
        Paragraph("Acél keresztmetszet ellenőrző - EC3", styles["Title"]),
        Spacer(1, 20),

        Paragraph("Keresztmetszet", styles["Heading2"]),
        Spacer(1, 8),

        Table([
            ["Szelvény", szelveny_nev],
            ["Acélminőség", anyag],
            ["fy [MPa]", f"{fy:.0f}"],
            ["h [mm]", f'{szelveny["h"]:.1f}'],
            ["b [mm]", f'{szelveny["b"]:.1f}'],
            ["tw [mm]", f'{szelveny["tw"]:.1f}'],
            ["tf [mm]", f'{szelveny["tf"]:.1f}'],
            ["A [cm2]", f'{szelveny["A"]:.2f}'],
        ]),

        Spacer(1, 20),

        Paragraph("Igénybevételek", styles["Heading2"]),
        Spacer(1, 8),

        Table([
            ["NEd [kN]", f"{NEd:.2f}"],
            ["VyEd [kN]", f"{VyEd:.2f}"],
            ["VzEd [kN]", f"{VzEd:.2f}"],
            ["MyEd [kNm]", f"{MyEd:.2f}"],
            ["MzEd [kNm]", f"{MzEd:.2f}"],
            ["TEd [kNm]", f"{TEd:.2f}"],
        ]),
    ]
    if eredmeny_sorok:
        tartalom.append(Spacer(1, 20))
        tartalom.append(Paragraph("Eredmények összegzése", styles["Heading2"]))
        tartalom.append(Spacer(1, 8))

        eredmeny_tabla = Table(
            eredmeny_sorok,
            colWidths=[280, 90, 90]
        )

        tartalom.append(eredmeny_tabla)
    doc.build(tartalom)

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="EC3_dokumentacio.pdf",
        mimetype="application/pdf"
    )
    
if __name__ == "__main__":
    app.run(debug=True)