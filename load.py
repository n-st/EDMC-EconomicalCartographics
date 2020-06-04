# -*- coding: utf-8 -*-
#
# List planets that are worth mapping with a Deep Surface Scanner (i.e. their
# estimated scan reward, based on type, terraformability and first-discovery
# state, exceeds a given value).
#

from __future__ import print_function

from collections import defaultdict
import requests
import sys
import threading
try:
    # Python 2
    from urllib2 import quote
    import Tkinter as tk
except ModuleNotFoundError:
    # Python 3
    from urllib.parse import quote
    import tkinter as tk

from ttkHyperlinkLabel import HyperlinkLabel
import myNotebook as nb

if __debug__:
    from traceback import print_exc

from config import config
from l10n import Locale

import traceback

VERSION = '1.20'

SETTING_DEFAULT = 0x0002	# Earth-like
SETTING_EDSM    = 0x1000
SETTING_NONE    = 0xffff

WORLDS = [
    # Type    Black-body temp range  EDSM description
    ('Metal-Rich',      0,  1103.0, 'Metal-rich body'),
    ('Earth-Like',    278.0, 227.0, 'Earth-like world'),
    ('Water',         307.0, 156.0, 'Water world'),
    ('Ammonia',       193.0, 117.0, 'Ammonia world'),
    ('Terraformable', 315.0, 223.0, 'terraformable'),
]

LS = 300000000.0	# 1 ls in m (approx)

this = sys.modules[__name__]	# For holding module globals
this.frame = None
this.label = None
this.worlds = []
this.bodies = {}
this.minvalue = 0
this.edsm_session = None
this.edsm_data = None

# Used during preferences
this.settings = None
this.edsm_setting = None


def plugin_start3(plugin_dir):
    return plugin_start()

def plugin_start():
    # App isn't initialised at this point so can't do anything interesting
    return 'EconomicalCartographics'

def plugin_app(parent):
    # Create and display widgets
    config.set('ec_minvalue', 300000)
    this.minvalue = config.getint('ec_minvalue')
    this.label = tk.Label(parent, text='EC: no scans yet')
    return this.label

def plugin_prefs(parent, cmdr, is_beta):
    frame = nb.Frame(parent)
    nb.Label(frame, text = 'Display:').grid(row = 0, padx = 10, pady = (10,0), sticky=tk.W)

    setting = get_setting()
    this.settings = []
    row = 1
    for (name, high, low, subType) in WORLDS:
        var = tk.IntVar(value = (setting & row) and 1)
        nb.Checkbutton(frame, text = name, variable = var).grid(row = row, padx = 10, pady = 2, sticky=tk.W)
        this.settings.append(var)
        row *= 2

    nb.Label(frame, text = 'Elite Dangerous Star Map:').grid(padx = 10, pady = (10,0), sticky=tk.W)
    this.edsm_setting = tk.IntVar(value = (setting & SETTING_EDSM) and 1)
    nb.Checkbutton(frame, text = 'Look up system in EDSM database', variable = this.edsm_setting).grid(padx = 10, pady = 2, sticky=tk.W)

    nb.Label(frame, text = 'Version %s' % VERSION).grid(padx = 10, pady = 10, sticky=tk.W)

    return frame

def prefs_changed(cmdr, is_beta):
    row = 1
    setting = 0
    for var in this.settings:
        setting += var.get() and row
        row *= 2

    setting += this.edsm_setting.get() and SETTING_EDSM
    config.set('habzone', setting or SETTING_NONE)
    this.settings = None
    this.edsm_setting = None

#def get_planetclass_k(planetclass: str, terraformable: bool):
def get_planetclass_k(planetclass, terraformable):
    if planetclass == 'Metal rich body':
        return 21790
    elif planetclass == 'Ammonia world':
        return 96932
    elif planetclass == 'Sudarsky class I gas giant':
        return 1656
    elif planetclass == 'Sudarsky class II gas giant' or planetclass == 'High metal content body':
        if terraformable:
            return 100677
        else:
            return 9654
    elif planetclass == 'Water world' or planetclass == 'Earthlike body':
        if terraformable:
            return 116295
        else:
            return 64831
    else:
        if terraformable:
            return 93328
        else:
            return 300

#def get_body_value(k: int, mass: float, isFirstDicoverer: bool, isFirstMapper: bool):
def get_body_value(k, mass, isFirstDicoverer, isFirstMapper):
    """
        Adapted from MattG's example code at https://forums.frontier.co.uk/threads/exploration-value-formulae.232000/
        Thank you, MattG! :)
    """
    q = 0.56591828
    mappingMultiplier = 1
    efficiencyBonus = 1.25

    # deviation from original: we want to know what the body would yield *if*
    # we would map it, so we skip the "isMapped" check
    if isFirstDicoverer and isFirstMapper:
        # note the additional multiplier later (hence the lower multiplier here)
        mappingMultiplier = 3.699622554
    elif isFirstMapper:
        mappingMultiplier = 8.0956
    else:
        mappingMultiplier = 3.3333333333

    mappingMultiplier *= efficiencyBonus

    value = max(500, (k + k * q * (mass ** 0.2)) * mappingMultiplier)
    if isFirstDicoverer:
        value *= 2.6
    return int(value)

def format_credits(credits, space = True):
    if credits > 9999999:
        # 12 MCr
        s = '%.0f MCr' % (credits / 1000000.0)
    elif credits > 999999:
        # 1.3 MCr
        s = '%.1f MCr' % (credits / 1000000.0)
    elif credits > 999:
        # 456 kCr
        s = '%.0f kCr' % (credits / 1000.0)
    else:
        # 789 Cr
        s = '%.0f Cr' % (credits)

    if not space:
        s = s.replace(' ', '')

    return s

def format_ls(ls, space = True):
    if ls > 9999999:
        # 12 Mls
        s = '%.0f Mls' % (ls / 1000000.0)
    elif ls > 999999:
        # 1.3 Mls
        s = '%.1f Mls' % (ls / 1000000.0)
    elif ls > 999:
        # 456 kls
        s = '%.0f kls' % (ls / 1000.0)
    else:
        # 789 ls
        s = '%.0f ls' % (ls)

    if not space:
        s = s.replace(' ', '')

    return s

def journal_entry(cmdr, is_beta, system, station, entry, state):

    if entry['event'] == 'Scan':
        #{
        #    "timestamp": "2020-06-04T16:38:38Z",
        #    "event": "Scan",
        #    "ScanType": "Detailed",
        #>   "BodyName": "Hypiae Aec QN-B d0 6",
        #    "BodyID": 6,
        #    "Parents": [{
        #        "Star": 0
        #    }],
        #>   "StarSystem": "Hypiae Aec QN-B d0",
        #    "SystemAddress": 10846602755,
        #>   "DistanceFromArrivalLS": 1853.988159,
        #    "TidalLock": false,
        #>   "TerraformState": "Terraformable",
        #>   "PlanetClass": "High metal content body",
        #    "Atmosphere": "thin sulfur dioxide atmosphere",
        #    "AtmosphereType": "SulphurDioxide",
        #    "AtmosphereComposition": [{
        #        "Name": "SulphurDioxide",
        #        "Percent": 100.000000
        #    }],
        #    "Volcanism": "",
        #>   "MassEM": 0.082886,
        #    "Radius": 2803674.500000,
        #    "SurfaceGravity": 4.202756,
        #    "SurfaceTemperature": 235.028137,
        #    "SurfacePressure": 252.739502,
        #    "Landable": false,
        #    "Composition": {
        #        "Ice": 0.000000,
        #        "Rock": 0.670286,
        #        "Metal": 0.329714
        #    },
        #    "SemiMajorAxis": 546118336512.000000,
        #    "Eccentricity": 0.018082,
        #    "OrbitalInclination": -0.015393,
        #    "Periapsis": 288.791321,
        #    "OrbitalPeriod": 169821040.000000,
        #    "RotationPeriod": 151855.375000,
        #    "AxialTilt": -0.505372,
        #>   "WasDiscovered": false,
        #>   "WasMapped": false
        #}

        if not 'PlanetClass' in entry:
            # That's no moon!
            return

        try:
            # If we get any key-not-in-dict errors, then this body probably
            # wasn't interesting in the first place
            starsystem = entry['StarSystem']
            bodyname = entry['BodyName']
            terraformable = bool(entry['TerraformState'])
            distancels = float(entry['DistanceFromArrivalLS'])
            planetclass = entry['PlanetClass']
            mass = float(entry['MassEM'])
            was_discovered = bool(entry['WasDiscovered'])
            was_mapped = bool(entry['WasMapped'])

            if bodyname.startswith(starsystem + ' '):
                bodyname_insystem = bodyname[len(starsystem + ' '):]
            else:
                bodyname_insystem = bodyname

            k = get_planetclass_k(planetclass, terraformable)
            value = get_body_value(k, mass, not was_discovered, not was_mapped)

            this.bodies[bodyname_insystem] = (value, distancels)

            #sorted_bodies = sorted(this.bodies, key = lambda x: x[1])
            sorted_body_names = [k
                    for k, v
                    in sorted(
                        this.bodies.items(),
                        key=lambda item: item[1][1] # take: value (item[1]), which is a tuple -> second of tuple ([1]), which is the distance
                        )
                    ]

            def format_body(body_name):
                body_value = this.bodies[body_name][0]
                body_distance = this.bodies[body_name][1]
                if body_value >= this.minvalue:
                    return '%s (%s, %s)' % \
                        (body_name,
                        format_credits(body_value, False),
                        format_ls(body_distance, False))
                else:
                    return '%s' % (body_name)

            # template: NAME (VALUE, DIST), …
            this.label['text'] = 'EC: %s' % \
                    (', '.join(
                        [format_body(b) for b in sorted_body_names]
                        )
                    )

            #this.label['text'] += ' %s (%.0f Cr)' % (bodyname_insystem, format_credits(value, False))

        except Exception as e:
            traceback.print_exc()
            print(e)

    elif entry['event'] == 'FSDJump':
        this.bodies = {}
        this.label['text'] = 'EC: no scans yet'

def get_setting():
    setting = config.getint('habzone')
    if setting == 0:
        return SETTING_DEFAULT	# Default to Earth-Like
    elif setting == SETTING_NONE:
        return 0	# Explicitly set by the user to display nothing
    else:
        return setting

