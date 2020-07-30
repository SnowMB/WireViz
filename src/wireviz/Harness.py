#!/usr/bin/env python
# -*- coding: utf-8 -*-

from wireviz.DataClasses import Connector, Cable
#from graphviz import Graph
from pydot import graph_from_dot_data, Dot, Node, Edge
from wireviz import wv_colors, wv_helper
from wireviz.wv_colors import get_color_hex
from wireviz.wv_helper import awg_equiv, mm2_equiv, tuplelist2tsv, \
    nested_html_table, flatten2d, index_if_list, html_line_breaks, \
    graphviz_line_breaks, remove_line_breaks, open_file_read, open_file_write, \
    manufacturer_info_field
from collections import Counter
from typing import List
from pathlib import Path
import re



#---------------------------------------------------pydot helper functions
WIRE_ATTRIBUTE="wv_wire"
WIRE_SPLINE_ATTRIBUTE="wv_wire_spline"
WIRE_COLOR_ATTRIBUTE="wv_color"







def stringToPoint(str):
  return tuple(float(n) for n in str.split(","))

def stringToPoints(str):
  str = str.replace('"', '')
  return list(stringToPoint(s) for s in str.split(" "))

def pointsToString(points):
  return " ".join("{},{}".format(round(p[0],3),round(p[1],3)) for p in points)


def calcPointsinBewteen(l, r):
  diff_x = (r[0]-l[0])/3
  diff_y = (r[1]-l[1])/3

  return [(l[0]+diff_x, l[1]+diff_y), (l[0]+2*diff_x, l[1]+2*diff_y)]

def combineSplines(*splines):
  spline = splines[0]

  for i in range(1, len(splines)):
    l = splines[i-1][-1]
    r = splines[i][0]

    spline.extend(calcPointsinBewteen(l, r))
    spline.extend(splines[i])

  return spline


def combineEdge(*edges):
  #print("COMBINE_EDGES")

  splines = [stringToPoints(e.get("pos")) for e in edges]

  spline = combineSplines(*splines)

  e = Edge(edges[0].get_source(),edges[-1].get_destination())
  e.set("pos", pointsToString(spline))

  return e

def combineGraphEdges(*edges):
  from itertools import groupby

  newEdges = []
  edges = sorted(*edges, key=lambda e: int(e.get(WIRE_ATTRIBUTE)))
  for ref, idx in groupby(edges, lambda e: int(e.get(WIRE_ATTRIBUTE))):
    l = list(idx)
    #print(ref, " : ", l)
    l.sort(key=lambda e: e.get(WIRE_SPLINE_ATTRIBUTE))

    wire = l[0].get(WIRE_ATTRIBUTE)
    colors = wv_colors.get_color_hex(l[0].get(WIRE_COLOR_ATTRIBUTE))

    e = combineEdge(*l)
    e.set_penwidth("4.0")
    newEdges.append(e)

    
    e_color1 = Edge(e.get_source(), e.get_destination(), pos=e.get_pos(), penwidth="3.0", color=colors[0])
    newEdges.append(e_color1)

    if len(colors) > 1:
        e_color2 = Edge(e.get_source(), e.get_destination(), pos=e.get_pos(), penwidth="3.0", color=colors[1], style="dashed")
        newEdges.append(e_color2)
  
  return newEdges
#---------------------------------------------------















class Harness:

    def __init__(self):
        self.color_mode = 'SHORT'
        self.connectors = {}
        self.cables = {}
        self.additional_bom_items = []

    def add_connector(self, name: str, *args, **kwargs) -> None:
        self.connectors[name] = Connector(name, *args, **kwargs)

    def add_cable(self, name: str, *args, **kwargs) -> None:
        self.cables[name] = Cable(name, *args, **kwargs)

    def add_bom_item(self, item: dict) -> None:
        self.additional_bom_items.append(item)

    def connect(self, from_name: str, from_pin: (int, str), via_name: str, via_pin: (int, str), to_name: str, to_pin: (int, str)) -> None:
        for (name, pin) in zip([from_name, to_name], [from_pin, to_pin]):  # check from and to connectors
            if name is not None and name in self.connectors:
                connector = self.connectors[name]
                if pin in connector.pins and pin in connector.pinlabels:
                    if connector.pins.index(pin) == connector.pinlabels.index(pin):
                        # TODO: Maybe issue a warning? It's not worthy of an exception if it's unambiguous, but maybe risky?
                        pass
                    else:
                        raise Exception(f'{name}:{pin} is defined both in pinlabels and pins, for different pins.')
                if pin in connector.pinlabels:
                    if connector.pinlabels.count(pin) > 1:
                        raise Exception(f'{name}:{pin} is defined more than once.')
                    else:
                        index = connector.pinlabels.index(pin)
                        pin = connector.pins[index] # map pin name to pin number
                        if name == from_name:
                            from_pin = pin
                        if name == to_name:
                            to_pin = pin
                if not pin in connector.pins:
                    raise Exception(f'{name}:{pin} not found.')

        self.cables[via_name].connect(from_name, from_pin, via_pin, to_name, to_pin)
        if from_name in self.connectors:
            self.connectors[from_name].activate_pin(from_pin)
        if to_name in self.connectors:
            self.connectors[to_name].activate_pin(to_pin)

    def create_graph(self) -> Dot:
        font = 'arial'
        dot = Dot(graph_type='graph')
        dot.set_graph_defaults(rankdir='LR',
                 ranksep='2',
                 bgcolor='white',
                 nodesep='0.33',
                 fontname=font)
        #dot.body.append('// Graph generated by WireViz')
        #dot.body.append('// https://github.com/formatc1702/WireViz')
        dot.set_node_defaults(shape='record',
                 style='filled',
                 fillcolor='white',
                 fontname=font)
        dot.set_edge_defaults(style='bold',
                 fontname=font)

        # prepare ports on connectors depending on which side they will connect
        for _, cable in self.cables.items():
            for connection_color in cable.connections:
                if connection_color.from_port is not None:  # connect to left
                    self.connectors[connection_color.from_name].ports_right = True
                if connection_color.to_port is not None:  # connect to right
                    self.connectors[connection_color.to_name].ports_left = True

        for key, connector in self.connectors.items():

            rows = [[connector.name if connector.show_name else None],
                    [f'P/N: {connector.pn}' if connector.pn else None,
                     manufacturer_info_field(connector.manufacturer, connector.mpn)],
                    [html_line_breaks(connector.type),
                     html_line_breaks(connector.subtype),
                     f'{connector.pincount}-pin' if connector.show_pincount else None,
                     connector.color, '<!-- colorbar -->' if connector.color else None],
                    '<!-- connector table -->' if connector.style != 'simple' else None,
                    [html_line_breaks(connector.notes)]]
            html = nested_html_table(rows)

            if connector.color: # add color bar next to color info, if present
                colorbar = f' bgcolor="{wv_colors.translate_color(connector.color, "HEX")}" width="4"></td>' # leave out '<td' from string to preserve any existing attributes of the <td> tag
                html = html.replace('><!-- colorbar --></td>', colorbar)

            if connector.style != 'simple':
                pinlist = []
                for pin, pinlabel in zip(connector.pins, connector.pinlabels):
                    if connector.hide_disconnected_pins and not connector.visible_pins.get(pin, False):
                        continue
                    pinlist.append([f'<td port="p{pin}l">{pin}</td>' if connector.ports_left else None,
                                    f'<td>{pinlabel}</td>' if pinlabel else '',
                                    f'<td port="p{pin}r">{pin}</td>' if connector.ports_right else None])

                pinhtml = '<table border="0" cellspacing="0" cellpadding="3" cellborder="1">'
                for i, pin in enumerate(pinlist):
                    pinhtml = f'{pinhtml}<tr>'
                    for column in pin:
                        if column is not None:
                            pinhtml = f'{pinhtml}{column}'
                    pinhtml = f'{pinhtml}</tr>'
                pinhtml = f'{pinhtml}</table>'
                html = html.replace('<!-- connector table -->', pinhtml)

            n = Node(key, label=f'<{html}>', shape='none', margin='0', style='filled', fillcolor='white')
            dot.add_node( n )

            if len(connector.loops) > 0:
                dot.set_edge_defaults(color='#000000:#ffffff:#000000')
                if connector.ports_left:
                    loop_side = 'l'
                    loop_dir = 'w'
                elif connector.ports_right:
                    loop_side = 'r'
                    loop_dir = 'e'
                else:
                    raise Exception('No side for loops')
                for loop in connector.loops:
                    e = Edge(f'{connector.name}:p{loop[0]}{loop_side}:{loop_dir}',
                             f'{connector.name}:p{loop[1]}{loop_side}:{loop_dir}')
                    dot.add_edge(e)

        wire_id = 0
        wire_spline_id = 0
        for _, cable in self.cables.items():

            awg_fmt = ''
            if cable.show_equiv:
                # Only convert units we actually know about, i.e. currently
                # mm2 and awg --- other units _are_ technically allowed,
                # and passed through as-is.
                if cable.gauge_unit =='mm\u00B2':
                    awg_fmt = f' ({awg_equiv(cable.gauge)} AWG)'
                elif cable.gauge_unit.upper() == 'AWG':
                    awg_fmt = f' ({mm2_equiv(cable.gauge)} mm\u00B2)'

            identification = [f'P/N: {cable.pn}' if (cable.pn and not isinstance(cable.pn, list)) else '',
                              manufacturer_info_field(cable.manufacturer if not isinstance(cable.manufacturer, list) else None,
                                                      cable.mpn if not isinstance(cable.mpn, list) else None)]
            identification = list(filter(None, identification))

            attributes = [html_line_breaks(cable.type) if cable.type else '',
                          f'{len(cable.colors)}x' if cable.show_wirecount else '',
                          f'{cable.gauge} {cable.gauge_unit}{awg_fmt}' if cable.gauge else '',
                          '+ S' if cable.shield else '',
                          f'{cable.length} m' if cable.length > 0 else '']
            attributes = list(filter(None, attributes))

            html = '<table border="0" cellspacing="0" cellpadding="0">'  # main table

            if cable.show_name or len(attributes) > 0:
                html = f'{html}<tr><td><table border="0" cellspacing="0" cellpadding="3" cellborder="1">'  # name+attributes table
                if cable.show_name:
                    html = f'{html}<tr><td colspan="{max(len(attributes), 1)}">{cable.name}</td></tr>'
                if(len(identification) > 0):  # print an identification row if values specified
                    html = f'{html}<tr><td colspan="{len(attributes)}" cellpadding="0"><table border="0" cellspacing="0" cellpadding="3" cellborder="1"><tr>'
                    for attrib in identification[0:-1]:
                        html = f'{html}<td sides="R">{attrib}</td>' # all columns except last have a border on the right (sides="R")
                    if len(identification) > 0:
                        html = f'{html}<td border="0">{identification[-1]}</td>' # last column has no border on the right because the enclosing table borders it
                    html = f'{html}</tr></table></td></tr>'  # end identification row
                if(len(attributes) > 0):
                    html = f'{html}<tr>'  # attribute row
                    for attrib in attributes:
                        html = f'{html}<td balign="left">{attrib}</td>'
                    html = f'{html}</tr>'  # attribute row
                html = f'{html}</table></td></tr>'  # name+attributes table

            html = f'{html}<tr><td>&nbsp;</td></tr>'  # spacer between attributes and wires

            html = f'{html}<tr><td><table border="0" cellspacing="0" cellborder="0">'  # conductor table

            # determine if there are double- or triple-colored wires;
            # if so, pad single-color wires to make all wires of equal thickness
            colorlengths = list(map(len, cable.colors))
            pad = 4 in colorlengths or 6 in colorlengths

            for i, connection_color in enumerate(cable.colors, 1):
                p = []
                p.append(f'<!-- {i}_in -->')
                p.append(wv_colors.translate_color(connection_color, self.color_mode))
                p.append(f'<!-- {i}_out -->')
                html = f'{html}<tr>'
                for bla in p:
                    html = f'{html}<td>{bla}</td>'
                html = f'{html}</tr>'

                bgcolors = get_color_hex(connection_color, pad=pad)
                html = f'{html}<tr><td colspan="{len(p)}" border="0" cellspacing="0" cellpadding="0" port="w{i}" height="6">'
                #for j, bgcolor in enumerate(bgcolors[::-1]):  # Reverse to match the curved wires when more than 2 colors
                #    html = f'{html}<tr><td colspan="{len(p)}" cellpadding="0" height="2" bgcolor="{bgcolor if bgcolor != "" else wv_colors.default_color}" border="0"></td></tr>'
                html = html + '</td></tr>'
                if(cable.category == 'bundle'):  # for bundles individual wires can have part information
                    # create a list of wire parameters
                    wireidentification = []
                    if isinstance(cable.pn, list):
                        wireidentification.append(f'P/N: {cable.pn[i - 1]}')
                    manufacturer_info = manufacturer_info_field(cable.manufacturer[i - 1] if isinstance(cable.manufacturer, list) else None,
                                                                      cable.mpn[i - 1] if isinstance(cable.mpn, list) else None)
                    if manufacturer_info:
                        wireidentification.append(manufacturer_info)
                    # print parameters into a table row under the wire
                    if(len(wireidentification) > 0):
                        html = f'{html}<tr><td colspan="{len(p)}"><table border="0" cellspacing="0" cellborder="0"><tr>'
                        for attrib in wireidentification:
                            html = f'{html}<td>{attrib}</td>'
                        html = f'{html}</tr></table></td></tr>'

            if cable.shield:
                p = ['<!-- s_in -->', 'Shield', '<!-- s_out -->']
                html = f'{html}<tr><td>&nbsp;</td></tr>'  # spacer
                html = f'{html}<tr>'
                for bla in p:
                    html = html + f'<td>{bla}</td>'
                html = f'{html}</tr>'
                html = f'{html}<tr><td colspan="{len(p)}" cellpadding="0" height="6" border="2" sides="b" port="ws"></td></tr>'

            html = f'{html}<tr><td>&nbsp;</td></tr>'  # spacer at the end

            html = f'{html}</table>'  # conductor table

            html = f'{html}</td></tr>'  # main table
            if cable.notes:
                html = f'{html}<tr><td cellpadding="3" balign="left">{html_line_breaks(cable.notes)}</td></tr>'  # notes table
                html = f'{html}<tr><td>&nbsp;</td></tr>'  # spacer at the end

            html = f'{html}</table>'  # main table

            # connections
            for connection_color in cable.connections:
                wire_spline_id = 0
                if connection_color.from_port is not None:  # connect to left
                    from_port = f':p{connection_color.from_port}r' if self.connectors[connection_color.from_name].style != 'simple' else ''
                    #code_left_1 = f'"{connection_color.from_name}"{from_port}:e'
                    #code_left_2 = f'"{cable.name}":w{connection_color.via_port}:w'
                    code_left_1 = f'"{connection_color.from_name}"{from_port}'
                    code_left_2 = f'"{cable.name}":w{connection_color.via_port}'
                    e = Edge(code_left_1, code_left_2)

                    e.set(WIRE_ATTRIBUTE, str(wire_id))
                    e.set(WIRE_SPLINE_ATTRIBUTE, str(wire_spline_id))
                    wire_spline_id = wire_spline_id + 1
                    if isinstance(connection_color.via_port, int):  # check if it's an actual wire and not a shield
                        e.set(WIRE_COLOR_ATTRIBUTE, cable.colors[connection_color.via_port - 1])
                    else:  # it's a shield connection
                        # shield is shown as a thin tinned wire
                        e.set(WIRE_COLOR_ATTRIBUTE, 'SN')
                        #dot.set_edge_defaults(color=':'.join(['#000000', wv_colors.get_color_hex('SN', pad=False)[0], '#000000']))
                    
                    dot.add_edge(e)
                    from_string = f'{connection_color.from_name}:{connection_color.from_port}' if self.connectors[connection_color.from_name].show_name else ''
                    html = html.replace(f'<!-- {connection_color.via_port}_in -->', from_string)
                    
                if connection_color.to_port is not None:  # connect to right
                    to_port = f':p{connection_color.to_port}l' if self.connectors[connection_color.to_name].style != 'simple' else ''
                    #code_right_1 = f'{cable.name}:w{connection_color.via_port}:e'
                    #code_right_2 = f'{connection_color.to_name}{to_port}:w'
                    code_right_1 = f'"{cable.name}":w{connection_color.via_port}'
                    code_right_2 = f'"{connection_color.to_name}"{to_port}'
                    e = Edge(code_right_1, code_right_2)

                    e.set(WIRE_ATTRIBUTE, str(wire_id))
                    e.set(WIRE_SPLINE_ATTRIBUTE, str(wire_spline_id))
                    wire_spline_id = wire_spline_id + 1

                    dot.add_edge(e)
                    to_string = f'{connection_color.to_name}:{connection_color.to_port}' if self.connectors[connection_color.to_name].show_name else ''
                    html = html.replace(f'<!-- {connection_color.via_port}_out -->', to_string)
                
                wire_id = wire_id + 1

            n = Node(cable.name, label=f'<{html}>', shape='box', style='\"filled,dashed\"' if cable.category == 'bundle' else '', margin='0', fillcolor='white')
            dot.add_node(n)


        g = graph_from_dot_data(dot.create_dot(prog="dot", f="dot").decode('utf-8'))[0]

        newEdges = combineGraphEdges(g.get_edges())

        #plot new graph
        g2 = Dot(rankdir="LR", outputorder="nodesfirst")
        g2.set_type("graph")

        #copy nodes
        for n in g.get_nodes():
            g2.add_node(n)

        #add combined edges
        for e in newEdges:
            g2.add_edge(e)

        return g2

    @property
    def png(self):
        from io import BytesIO
        graph = self.create_graph()
        data = BytesIO()
        data.write(graph.create(f='png', prog=['neato', '-n2']))
        data.seek(0)
        return data.read()

    @property
    def svg(self):
        from io import BytesIO
        graph = self.create_graph()
        data = BytesIO()
        data.write(graph.create(f='svg', prog=['neato', '-n2']))
        data.seek(0)
        return data.read()

    def output(self, filename: (str, Path), view: bool = False, cleanup: bool = True, fmt: tuple = ('pdf', )) -> None:
        # graphical output
        graph = self.create_graph()

        print (graph)
        print (filename)
        for f in fmt:
            graph.write(str(filename)+"."+f, format=f, prog=["neato", "-n2"])
            #graph.format = f
            #graph.render(filename=filename, view=view, cleanup=cleanup)
        graph.write_raw(f'{filename}.gv')
        # bom output
        bom_list = self.bom_list()
        with open_file_write(f'{filename}.bom.tsv') as file:
            file.write(tuplelist2tsv(bom_list))
        # HTML output
        with open_file_write(f'{filename}.html') as file:
            file.write('<!DOCTYPE html>\n')
            file.write('<html><head><meta charset="UTF-8"></head><body style="font-family:Arial">')

            file.write('<h1>Diagram</h1>')
            with open_file_read(f'{filename}.svg') as svg:
                file.write(re.sub(
                    '^<[?]xml [^?>]*[?]>[^<]*<!DOCTYPE [^>]*>',
                    '<!-- XML and DOCTYPE declarations from SVG file removed -->',
                    svg.read(1024), 1))
                for svgdata in svg:
                    file.write(svgdata)

            file.write('<h1>Bill of Materials</h1>')
            listy = flatten2d(bom_list)
            file.write('<table style="border:1px solid #000000; font-size: 14pt; border-spacing: 0px">')
            file.write('<tr>')
            for item in listy[0]:
                file.write(f'<th align="left" style="border:1px solid #000000; padding: 8px">{item}</th>')
            file.write('</tr>')
            for row in listy[1:]:
                file.write('<tr>')
                for i, item in enumerate(row):
                    item_str = item.replace('\u00b2', '&sup2;')
                    align = 'align="right"' if listy[0][i] == 'Qty' else ''
                    file.write(f'<td {align} style="border:1px solid #000000; padding: 4px">{item_str}</td>')
                file.write('</tr>')
            file.write('</table>')

            file.write('</body></html>')

    def bom(self):
        bom = []
        bom_connectors = []
        bom_cables = []
        bom_extra = []
        # connectors
        connector_group = lambda c: (c.type, c.subtype, c.pincount, c.manufacturer, c.mpn, c.pn)
        for group in Counter([connector_group(v) for v in self.connectors.values()]):
            items = {k: v for k, v in self.connectors.items() if connector_group(v) == group}
            shared = next(iter(items.values()))
            designators = list(items.keys())
            designators.sort()
            conn_type = f', {remove_line_breaks(shared.type)}' if shared.type else ''
            conn_subtype = f', {remove_line_breaks(shared.subtype)}' if shared.subtype else ''
            conn_pincount = f', {shared.pincount} pins' if shared.style != 'simple' else ''
            conn_color = f', {shared.color}' if shared.color else ''
            name = f'Connector{conn_type}{conn_subtype}{conn_pincount}{conn_color}'
            item = {'item': name, 'qty': len(designators), 'unit': '', 'designators': designators if shared.show_name else '',
                    'manufacturer': shared.manufacturer, 'mpn': shared.mpn, 'pn': shared.pn}
            bom_connectors.append(item)
            bom_connectors = sorted(bom_connectors, key=lambda k: k['item'])  # https://stackoverflow.com/a/73050
        bom.extend(bom_connectors)
        # cables
        # TODO: If category can have other non-empty values than 'bundle', maybe it should be part of item name?
        # The category needs to be included in cable_group to keep the bundles excluded.
        cable_group = lambda c: (c.category, c.type, c.gauge, c.gauge_unit, c.wirecount, c.shield, c.manufacturer, c.mpn, c.pn)
        for group in Counter([cable_group(v) for v in self.cables.values() if v.category != 'bundle']):
            items = {k: v for k, v in self.cables.items() if cable_group(v) == group}
            shared = next(iter(items.values()))
            designators = list(items.keys())
            designators.sort()
            total_length = sum(i.length for i in items.values())
            cable_type = f', {remove_line_breaks(shared.type)}' if shared.type else ''
            gauge_name = f' x {shared.gauge} {shared.gauge_unit}' if shared.gauge else ' wires'
            shield_name = ' shielded' if shared.shield else ''
            name = f'Cable{cable_type}, {shared.wirecount}{gauge_name}{shield_name}'
            item = {'item': name, 'qty': round(total_length, 3), 'unit': 'm', 'designators': designators,
                    'manufacturer': shared.manufacturer, 'mpn': shared.mpn, 'pn': shared.pn}
            bom_cables.append(item)
        # bundles (ignores wirecount)
        wirelist = []
        # list all cables again, since bundles are represented as wires internally, with the category='bundle' set
        for bundle in self.cables.values():
            if bundle.category == 'bundle':
                # add each wire from each bundle to the wirelist
                for index, color in enumerate(bundle.colors, 0):
                    wirelist.append({'type': bundle.type, 'gauge': bundle.gauge, 'gauge_unit': bundle.gauge_unit, 'length': bundle.length, 'color': color, 'designator': bundle.name,
                                     'manufacturer': index_if_list(bundle.manufacturer, index),
                                     'mpn': index_if_list(bundle.mpn, index),
                                     'pn': index_if_list(bundle.pn, index)})
        # join similar wires from all the bundles to a single BOM item
        wire_group = lambda w: (w.get('type', None), w['gauge'], w['gauge_unit'], w['color'], w['manufacturer'], w['mpn'], w['pn'])
        for group in Counter([wire_group(v) for v in wirelist]):
            items = [v for v in wirelist if wire_group(v) == group]
            shared = items[0]
            designators = [i['designator'] for i in items]
            designators = list(dict.fromkeys(designators))  # remove duplicates
            designators.sort()
            total_length = sum(i['length'] for i in items)
            wire_type = f', {remove_line_breaks(shared["type"])}' if shared.get('type', None) else ''
            gauge_name = f', {shared["gauge"]} {shared["gauge_unit"]}' if shared.get('gauge', None) else ''
            gauge_color = f', {shared["color"]}' if 'color' in shared != '' else ''
            name = f'Wire{wire_type}{gauge_name}{gauge_color}'
            item = {'item': name, 'qty': round(total_length, 3), 'unit': 'm', 'designators': designators,
                    'manufacturer': shared['manufacturer'], 'mpn': shared['mpn'], 'pn': shared['pn']}
            bom_cables.append(item)
            bom_cables = sorted(bom_cables, key=lambda k: k['item'])  # sort list of dicts by their values (https://stackoverflow.com/a/73050)
        bom.extend(bom_cables)

        for item in self.additional_bom_items:
            name = item['description'] if item.get('description', None) else ''
            if isinstance(item.get('designators', None), List):
                item['designators'].sort()  # sort designators if a list is provided
            item = {'item': name, 'qty': item.get('qty', None), 'unit': item.get('unit', None), 'designators': item.get('designators', None),
                    'manufacturer': item.get('manufacturer', None), 'mpn': item.get('mpn', None), 'pn': item.get('pn', None)}
            bom_extra.append(item)
        bom_extra = sorted(bom_extra, key=lambda k: k['item'])
        bom.extend(bom_extra)
        return bom

    def bom_list(self):
        bom = self.bom()
        keys = ['item', 'qty', 'unit', 'designators'] # these BOM columns will always be included
        for fieldname in ['pn', 'manufacturer', 'mpn']: # these optional BOM columns will only be included if at least one BOM item actually uses them
            if any(fieldname in x and x.get(fieldname, None) for x in bom):
                keys.append(fieldname)
        bom_list = []
        # list of staic bom header names,  headers not specified here are generated by capitilising the internal name
        bom_headings = {
            "pn": "P/N",
            "mpn": "MPN"
        }
        bom_list.append([(bom_headings[k] if k in bom_headings else k.capitalize()) for k in keys])  # create header row with keys
        for item in bom:
            item_list = [item.get(key, '') for key in keys]  # fill missing values with blanks
            item_list = [', '.join(subitem) if isinstance(subitem, List) else subitem for subitem in item_list]  # convert any lists into comma separated strings
            item_list = ['' if subitem is None else subitem for subitem in item_list]  # if a field is missing for some (but not all) BOM items
            bom_list.append(item_list)
        return bom_list
