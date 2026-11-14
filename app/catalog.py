from .models import Investigation


NASA_PSI_SOURCE = "https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation"


SEED_INVESTIGATIONS = [
    Investigation(
        id="BASS",
        name="Burning and Suppression of Solids",
        description="Studies ignition, flame spread, and suppression of solid materials in reduced gravity.",
        domain="flammability",
        gravity=["microgravity", "normal gravity"],
        fuels=["fabrics", "plastics", "solid materials"],
        conditions=["elevated oxygen", "fan-driven airflow"],
        measurements=["flame spread", "ignition", "extinction time", "temperature"],
        hardware=["Microgravity Science Glovebox", "fan-driven flow duct"],
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/BASS",
        keywords=["flammability", "material selection", "fire prevention", "habitat"],
    ),
    Investigation(
        id="FLEX",
        name="Flame Extinguishment Experiment",
        description="Tests extinction of burning droplets using carbon dioxide and helium dilution.",
        domain="suppression",
        gravity=["microgravity"],
        fuels=["liquid fuel droplets"],
        conditions=["carbon dioxide dilution", "helium dilution", "reduced pressure"],
        measurements=["extinction diameter", "burning rate", "flame temperature"],
        hardware=["Multi-user Droplet Combustion Apparatus", "Combustion Integrated Rack"],
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/FLEX",
        keywords=["suppression", "extinguishment", "fire control", "crew safety"],
    ),
    Investigation(
        id="SAME",
        name="Smoke and Aerosol Measurement Experiment",
        description="Characterizes smoke and aerosol behavior to improve fire detection in microgravity.",
        domain="detection",
        gravity=["microgravity"],
        fuels=["solid material smoke"],
        conditions=["spacecraft-like airflow", "reduced gravity"],
        measurements=["particle size", "aerosol concentration", "optical response"],
        hardware=["smoke and aerosol sensors"],
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/SAME",
        keywords=["smoke detection", "alarm", "aerosol", "early warning"],
    ),
    Investigation(
        id="ACME-CFI",
        name="Cool Flames Investigation",
        description="Examines gaseous flames and cool-flame chemistry across high oxygen concentrations.",
        domain="fundamental",
        gravity=["microgravity"],
        fuels=["propane", "gaseous fuels"],
        conditions=["up to 85 percent oxygen", "nitrogen dilution", "spherical burner"],
        measurements=["flame temperature", "chemical species", "flame structure"],
        hardware=["Combustion Integrated Rack", "spherical burner"],
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/CFI",
        keywords=["oxygen concentration", "flammability limits", "lunar habitat", "chemistry"],
    ),
    Investigation(
        id="BRE",
        name="Burning Rate Emulator",
        description="Measures gaseous-fuel burning behavior as a proxy for material flammability properties.",
        domain="flammability",
        gravity=["microgravity"],
        fuels=["gaseous fuels"],
        conditions=["still atmosphere", "controlled oxygen concentration"],
        measurements=["burning rate", "flame temperature", "extinction"],
        hardware=["Combustion Integrated Rack"],
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/BRE",
        keywords=["predictive modeling", "material properties", "flammability"],
    ),
]


def get_catalog() -> list[Investigation]:
    return SEED_INVESTIGATIONS.copy()
