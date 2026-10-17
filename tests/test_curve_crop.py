"""Spanning curve ink is independent of Verovio's measure content boxes."""
from xml.etree import ElementTree as ET

import pytest
import verovio

from score_cli.render_measure import _find_rendered_measures, _find_content_box


@pytest.mark.parametrize('family', ['slur', 'tie'])
def test_measure_crop_contains_curve_above_its_beamed_notes(family):
    paired = 'tied' if family == 'tie' else 'slur'
    midi_start = '<tie type="start"/>' if family == 'tie' else ''
    midi_stop = '<tie type="stop"/>' if family == 'tie' else ''
    xml = f'''<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>2</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><note><pitch><step>C</step><octave>5</octave></pitch><duration>8</duration><type>whole</type></note></measure><measure number="2"><note><pitch><step>E</step><octave>5</octave></pitch><duration>1</duration>{midi_start}<type>eighth</type><stem>up</stem><beam number="1">begin</beam><notations><{paired} type="start" number="1" placement="above"/></notations></note><note><pitch><step>{'E' if family == 'tie' else 'C'}</step><octave>5</octave></pitch><duration>1</duration>{midi_stop}<type>eighth</type><stem>up</stem><beam number="1">end</beam><notations><{paired} type="stop" number="1"/></notations></note><note><rest/><duration>6</duration><type>half</type><dot/></note></measure></part></score-partwise>'''
    toolkit = verovio.toolkit()
    toolkit.setOptions({'inputFrom': 'xml', 'svgBoundingBoxes': True,
                        'svgContentBoundingBoxes': True,
                        'svgAdditionalAttribute': ['measure@n']})
    assert toolkit.loadData(xml)
    svg = toolkit.renderToSVG(1)
    ns = '{http://www.w3.org/2000/svg}'
    groups = [g for g in ET.fromstring(svg).iter(ns + 'g')
              if family in g.get('class', '').split()
              and 'bounding-box' not in g.get('class', '').split()]
    assert len(groups) == 1
    curve = _find_content_box(groups[0], family, box_class='bounding-box')
    assert curve is not None
    measure = next(m for m in _find_rendered_measures(svg) if m.label == '2')
    assert measure.measure_box.y <= curve.y
    assert measure.measure_box.y + measure.measure_box.height >= curve.y + curve.height


@pytest.mark.parametrize('role', ['slur', 'tie', 'ending'])
@pytest.mark.parametrize('y,top,bottom', [(100, 100, 700), (800, 500, 1050)])
def test_cross_bar_control_extends_only_vertical_bounds_of_selected_bar(role, y, top, bottom):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg"><g class="system">
      <g class="system content-bounding-box"><rect x="0" y="0" width="600" height="900"/></g>
      <g class="measure" data-n="2"><g class="measure content-bounding-box"><rect x="100" y="500" width="100" height="200"/></g></g>
      <g class="{role}"><g class="{role} bounding-box"><rect x="50" y="{y}" width="200" height="250"/></g></g>
      <g class="{role}"><g class="{role} bounding-box"><rect x="400" y="-9999" width="50" height="20"/></g></g>
    </g></svg>'''
    measure = _find_rendered_measures(svg)[0]
    assert (measure.measure_box.x, measure.measure_box.width) == (100, 100)
    assert measure.measure_box.y == top  # Includes overlapping curve, not distant ink.
    assert measure.measure_box.y + measure.measure_box.height == bottom
