from flask import Flask, render_template, request
import csv
import math

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

    section_class = max(flange_class, web_class)

    eredmeny = None

    if request.args.get("szamitas") == "1":

        # --- NYOMÁSI ELLENÁLLÁS ---

        A_mm2 = szelveny["A"] * 100

        Nc_Rd = A_mm2 * fy / gamma_M0 / 1000

        kihasznaltsag_N = abs(NEd) / Nc_Rd


        # --- HAJLÍTÁSI ELLENÁLLÁS Y-Y ---

        Wpl_y_mm3 = szelveny["Wpl_y"] * 1000

        My_Rd = Wpl_y_mm3 * fy / gamma_M0 / 1_000_000

        kihasznaltsag_My = abs(MyEd) / My_Rd

        # --- HAJLÍTÁSI ELLENÁLLÁS Z-Z ---

        Wpl_z_mm3 = szelveny["Wpl_z"] * 1000

        Mz_Rd = Wpl_z_mm3 * fy / gamma_M0 / 1_000_000

        kihasznaltsag_Mz = abs(MzEd) / Mz_Rd

        # --- NYÍRÁSI ELLENÁLLÁS Vz ---

        Av_z_mm2 = szelveny["Av_z"] * 100

        Vz_Rd = Av_z_mm2 * fy / math.sqrt(3) / gamma_M0 / 1000

        kihasznaltsag_Vz = abs(VzEd) / Vz_Rd

        # --- NORMÁLERŐ + KÉTTENGELYŰ HAJLÍTÁS ---

        kihasznaltsag_NMM = (
            abs(NEd) / Nc_Rd
            + abs(MyEd) / My_Rd
            + abs(MzEd) / Mz_Rd
)

        # --- NYÍRÁSI ELLENÁLLÁS Vy ---

        Av_y_mm2 = 2 * szelveny["b"] * szelveny["tf"]

        Vy_Rd = Av_y_mm2 * fy / math.sqrt(3) / gamma_M0 / 1000

        kihasznaltsag_Vy = abs(VyEd) / Vy_Rd

        # --- CSAVARÁS ---

        csavaras_figyelmeztetes = None

        if abs(TEd) > 0:
            csavaras_figyelmeztetes = (
             "Csavarónyomaték van megadva. "
                "Nyitott I/H szelvény esetén a csavarási és vetemedési "
                "ellenőrzéshez további adatok / VEM vizsgálat szükséges."
    )

        # --- EREDMÉNYEK ---

        eredmeny = {
            "Nc_Rd": Nc_Rd,
            "kihasznaltsag": kihasznaltsag_N,
            "szazalek": kihasznaltsag_N * 100,
            "megfelel": kihasznaltsag_N <= 1.0,

            "My_Rd": My_Rd,
            "kihasznaltsag_My": kihasznaltsag_My,
            "szazalek_My": kihasznaltsag_My * 100,
            "megfelel_My": kihasznaltsag_My <= 1.0,

            "Mz_Rd": Mz_Rd,
            "kihasznaltsag_Mz": kihasznaltsag_Mz,
            "szazalek_Mz": kihasznaltsag_Mz * 100,
            "megfelel_Mz": kihasznaltsag_Mz <= 1.0,

            "NMM_kihasznaltsag": kihasznaltsag_NMM,
            "NMM_szazalek": kihasznaltsag_NMM * 100,
            "NMM_megfelel": kihasznaltsag_NMM <= 1.0,
            

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
    
if __name__ == "__main__":
    app.run(debug=True)