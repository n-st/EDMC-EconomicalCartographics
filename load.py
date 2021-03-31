# -*- coding: utf-8 -*-

# Economical Cartographics plugin for EDMC
# Source: https://github.com/n-st/EDMC-EconomicalCartographics
# Based on the Habitable Zone plugin by Jonathan Harris: https://github.com/Marginal/HabZone.
# Licensed under the [GNU Public License (GPL)](http://www.gnu.org/licenses/gpl-2.0.html) version 2 or later.

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

VERSION = '0.8'

this = sys.modules[__name__]	# For holding module globals
this.label = None
this.bodies = {}
this.minvalue = 0
this.starsystem = ''

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
    this.label = tk.Label(parent)
    update_display()
    return this.label

def plugin_prefs(parent, cmdr, is_beta):
    frame = nb.Frame(parent)
    nb.Label(frame, text = 'Display:').grid(row = 0, padx = 10, pady = (10,0), sticky=tk.W)

    setting = 0
    this.settings = []

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
    """
        Adapted from MattG's table at https://forums.frontier.co.uk/threads/exploration-value-formulae.232000/
        Thank you, MattG! :)
    """
    if planetclass == 'Metal rich body':
        return 21790
    elif planetclass == 'Ammonia world':
        return 96932
    elif planetclass == 'Sudarsky class I gas giant':
        return 1656
    elif planetclass == 'Sudarsky class II gas giant' or planetclass == 'High metal content body':
        if terraformable:
            return 9654+100677
        else:
            return 9654
    elif planetclass == 'Water world' or planetclass == 'Earthlike body':
        if terraformable:
            return 64831+116295
        else:
            return 64831
    else:
        if terraformable:
            return 300+93328
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

def format_unit(num, unit, space = True):
    if num > 9999999:
        # 12 Mu
        s = '%.0f M' % (num / 1000000.0)
    elif num > 999999:
        # 1.3 Mu
        s = '%.1f M' % (num / 1000000.0)
    elif num > 999:
        # 456 ku
        s = '%.0f k' % (num / 1000.0)
    else:
        # 789 u
        s = '%.0f ' % (num)

    if not space:
        s = s.replace(' ', '')

    s += unit

    return s

def format_credits(credits, space = True):
    return format_unit(credits, 'Cr', space)

def format_ls(ls, space = True):
    return format_unit(ls, 'ls', space)

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
            if 'StarSystem' in entry:
                this.starsystem = entry['StarSystem']
            bodyname = entry['BodyName']
            terraformable = bool(entry['TerraformState'])
            distancels = float(entry['DistanceFromArrivalLS'])
            planetclass = entry['PlanetClass']
            mass = float(entry['MassEM'])
            was_discovered = bool(entry['WasDiscovered'])
            was_mapped = bool(entry['WasMapped'])

            if bodyname.startswith(this.starsystem + ' '):
                bodyname_insystem = bodyname[len(this.starsystem + ' '):]
            else:
                bodyname_insystem = bodyname

            k = get_planetclass_k(planetclass, terraformable)
            value = get_body_value(k, mass, not was_discovered, not was_mapped)

            if bodyname_insystem in this.bodies and this.bodies[bodyname_insystem][0] < 0:
                # body exists and is hidden, preserve its "hidden" marker (value < 0)
                this.bodies[bodyname_insystem] = (this.bodies[bodyname_insystem][0], distancels)
            else:
                this.bodies[bodyname_insystem] = (value, distancels)

            update_display()

        except Exception as e:
            traceback.print_exc()
            print(e)

    elif entry['event'] == 'SAAScanComplete':
        bodyname = entry['BodyName']
        if bodyname.startswith(this.starsystem + ' '):
            bodyname_insystem = bodyname[len(this.starsystem + ' '):]
        else:
            bodyname_insystem = bodyname

        print('Hiding', bodyname_insystem)
        if bodyname_insystem in this.bodies:
            # body exists, only replace its value with a "hidden" marker
            this.bodies[bodyname_insystem] = (-1, this.bodies[bodyname_insystem][1])
        else:
            # body does not exist, add it as "hidden" (distance will hopefully filled by Scan event later)
            this.bodies[bodyname_insystem] = (-1, -1)

        update_display()

    elif entry['event'] == 'FSDJump':
        if 'StarSystem' in entry:
            this.starsystem = entry['StarSystem']
        this.bodies = {}
        update_display()

def update_display():
    valuable_body_names = [k
            for k, v
            in sorted(
                this.bodies.items(),
                # multi-key sorting:
                #   use only the value from the dict (item[1]), which is a tuple (credit_value, distance)
                #   key 1: credit_value < minvalue -- False < True when sorting, so >= minvalue will come first
                #   key 2: distance -- ascending
                key=lambda item: item[1][1]
                )
            if v[0] >= this.minvalue
            ]

    def format_body(body_name):
        # template: NAME (VALUE, DIST), …
        body_value = this.bodies[body_name][0]
        body_distance = this.bodies[body_name][1]
        if body_value >= this.minvalue:
            return '%s (%s, %s)' % \
                (body_name.upper(),
                format_credits(body_value, False),
                format_ls(body_distance, False))
        else:
            return '%s'

    if this.bodies:
        text = 'EC: '
        if valuable_body_names:
            text += ', '.join([format_body(b) for b in valuable_body_names])
            text += ' + '
        text += '#%d' % (len(this.bodies) - len(valuable_body_names))
        this.label['text'] = text
    else:
        this.label['text'] = 'EC: no scans yet'

