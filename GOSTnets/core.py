import os, sys, logging, warnings, time

import pyproj
import networkx as nx
import osmnx as ox
import pandas as pd
import geopandas as gpd
import numpy as np

from scipy import spatial
from functools import partial
from shapely.wkt import loads
from shapely.geometry import Point, LineString, MultiLineString, box
from shapely.ops import linemerge, unary_union, transform
from collections import Counter

def combo_csv_to_graph(fpath, u_tag = 'u', v_tag = 'v', geometry_tag = 'Wkt', largest_G = False):
    """
    Function for generating a G object from a saved combo .csv

    :param fpath: path to a .csv containing edges (WARNING: COMBO CSV only)
    :param u_tag: specify column containing u node ID if not labelled 'u'
    :param v_tag: specify column containing u node ID if not labelled 'v'
    :param geometry_tag: specify column containing u node ID if not
    :returns: a multidigraph object
    """

    edges_1 = pd.read_csv(os.path.join(fpath))

    edges = edges_1.copy()

    node_bunch = list(set(list(edges[u_tag]) + list(edges[v_tag])))

    col_list = list(edges.columns)
    drop_cols = [u_tag, v_tag, geometry_tag]
    attr_list = [col_entry for col_entry in col_list if col_entry not in drop_cols]

    def convert(x, attr_list):
        u = x[u_tag]
        v = x[v_tag]
        data = {'Wkt':loads(x[geometry_tag])}
        for i in attr_list:
            data[i] = x[i]

        return (u, v, data)

    edge_bunch = edges.apply(lambda x: convert(x, attr_list), axis = 1).tolist()

    G = nx.MultiDiGraph()

    G.add_nodes_from(node_bunch)
    G.add_edges_from(edge_bunch)

    for u, data in G.nodes(data = True):
        q = tuple(float(x) for x in u[1:-1].split(','))
        data['x'] = q[0]
        data['y'] = q[1]

    G = nx.convert_node_labels_to_integers(G)

    if largest_G == True:
        list_of_subgraphs = list(nx.strongly_connected_component_subgraphs(G))
        l = 0
        cur_max = 0
        for i in list_of_subgraphs:
            if i.number_of_edges() > cur_max:
                cur_max = i.number_of_edges()
                max_ID = l
            l +=1
        G = list_of_subgraphs[max_ID]

    return G

def edges_and_nodes_csv_to_graph(fpath_nodes, fpath_edges, u_tag = 'stnode', v_tag = 'endnode', geometry_tag = 'Wkt', largest_G = False):

    """
    Function for generating a G object from a saved .csv of edges

    :param fpath_nodes: 
      path to a .csv containing nodes
    :param fpath_edges: 
      path to a .csv containing edges
    :param u_tag: 
      optional. specify column containing u node ID if not labelled 'stnode'
    :param v_tag: 
      specify column containing v node ID if not labelled 'endnode'
    :param geometry_tag: 
      specify column containing geometry if not labelled 'Wkt'
    :returns: 
      a multidigraph object
    """

    nodes_df = pd.read_csv(fpath_nodes)
    edges_df = pd.read_csv(fpath_edges)

    chck_set = list(set(list(edges_df[u_tag]) + list(edges_df[v_tag])))

    def check(x, chck_set):
        if x in chck_set:
            return 1
        else:
            return 0

    nodes_df['chck'] = nodes_df['node_ID'].apply(lambda x: check(x, chck_set))

    nodes_df = nodes_df.loc[nodes_df.chck == 1]

    def convert_nodes(x):
        u = x.node_ID
        data = {'x':x.x,
               'y':x.y}
        return (u, data)

    node_bunch = nodes_df.apply(lambda x: convert_nodes(x), axis = 1).tolist()

    col_list = list(edges_df.columns)
    drop_cols = [u_tag, v_tag, geometry_tag]
    attr_list = [col_entry for col_entry in col_list if col_entry not in drop_cols]

    def convert_edges(x):
        u = x[u_tag]
        v = x[v_tag]
        data = {'Wkt':loads(x[geometry_tag])}
        for i in attr_list:
            data[i] = x[i]

        return (u, v, data)

    edge_bunch = edges_df.apply(lambda x: convert_edges(x), axis = 1).tolist()

    G = nx.MultiDiGraph()

    G.add_nodes_from(node_bunch)
    G.add_edges_from(edge_bunch)

    G = nx.convert_node_labels_to_integers(G)

    if largest_G == True:
        list_of_subgraphs = list(nx.strongly_connected_component_subgraphs(G))
        l = 0
        cur_max = 0
        for i in list_of_subgraphs:
            if i.number_of_edges() > cur_max:
                cur_max = i.number_of_edges()
                max_ID = l
            l +=1
        G = list_of_subgraphs[max_ID]

    return G

def node_gdf_from_graph(G, crs = {'init' :'epsg:4326'}, attr_list = None, geometry_tag = 'geometry', xCol='x', yCol='y'):
    """
    Function for generating GeoDataFrame from Graph

    :param G: a graph object G
    :param crs: projection of format {'init' :'epsg:4326'}. Defaults to WGS84. note: here we are defining the crs of the input geometry - we do NOT reproject to this crs. To reproject, consider using geopandas' to_crs method on the returned gdf.
    :param attr_list: list of the keys which you want to be moved over to the GeoDataFrame, if not all. Defaults to None, which will move all.
    :param geometry_tag: specify geometry attribute of graph, default 'geometry'
    :param xCol: if no shapely geometry but Longitude present, assign here
    :param yCol: if no shapely geometry but Latitude present, assign here
    :returns: a geodataframe of the node objects in the graph
    """

    nodes = []
    keys = []

    if attr_list is None:
        for u, data in G.nodes(data = True):
            keys.append(list(data.keys()))
        flatten = lambda l: [item for sublist in l for item in sublist]
        attr_list = list(set(flatten(keys)))

    if geometry_tag in attr_list:
        non_geom_attr_list = attr_list
        non_geom_attr_list.remove(geometry_tag)
    else:
        non_geom_attr_list = attr_list

    z = 0

    for u, data in G.nodes(data=True):

        if geometry_tag not in attr_list and xCol in attr_list and yCol in attr_list :
            try:
                new_column_info = {
                'node_ID': u,
                'geometry': Point(data[xCol], data[yCol]),
                'x': data[xCol],
                'y': data[yCol]}
            except:
                print('Skipped due to missing geometry data:',(u, data))
        else:
            try:
                new_column_info = {
                'node_ID': u,
                'geometry': data[geometry_tag],
                'x':data[geometry_tag].x,
                'y':data[geometry_tag].y}
            except:
                print((u, data))

        for i in non_geom_attr_list:
            try:
                new_column_info[i] = data[i]
            except:
                pass

        nodes.append(new_column_info)
        z += 1

    nodes_df = pd.DataFrame(nodes)
    nodes_df = nodes_df[['node_ID',*non_geom_attr_list,geometry_tag]]
    nodes_df = nodes_df.drop_duplicates(subset=['node_ID'], keep='first')
    nodes_gdf = gpd.GeoDataFrame(nodes_df, geometry=nodes_df.geometry, crs = crs)

    return nodes_gdf

def edge_gdf_from_graph(G, crs = {'init' :'epsg:4326'}, attr_list = None, geometry_tag = 'geometry', xCol='x', yCol = 'y'):
    """
    Function for generating a GeoDataFrame from a networkx Graph object

    :param G: (required) a graph object G
    :param crs: (optional) projection of format {'init' :'epsg:4326'}. Defaults to WGS84. Note: here we are defining the crs of the input geometry -we do NOT reproject to this crs. To reproject, consider using geopandas' to_crs method on the returned gdf.
    :param attr_list: (optional) list of the keys which you want to be moved over to the GeoDataFrame.
    :param geometry_tag: (optional) the key in the data dictionary for each edge which contains the geometry info.
    :param xCol: (optional) if no geometry is present in the edge data dictionary, the function will try to construct a straight line between the start and end nodes, if geometry information is present in their data dictionaries.  Pass the Longitude info as 'xCol'.
    :param yCol: (optional) likewise, determining the Latitude tag for the node's data dictionary allows us to make a straight line geometry where an actual geometry is missing.
    :returns: a GeoDataFrame object of the edges in the graph
    """

    edges = []
    keys = []

    if attr_list is None:
        for u, v, data in G.edges(data = True):
            keys.append(list(data.keys()))
        flatten = lambda l: [item for sublist in l for item in sublist]
        keys = list(set(flatten(keys)))
        if geometry_tag in keys:
            keys.remove(geometry_tag)
        attr_list = keys

    for u, v, data in G.edges(data=True):

        if geometry_tag in data:
            # if it has a geometry attribute (a list of line segments), add them
            # to the list of lines to plot
            geom = data[geometry_tag]

        else:
            # if it doesn't have a geometry attribute, the edge is a straight
            # line from node to node
            x1 = G.nodes[u][xCol]
            y1 = G.nodes[u][yCol]
            x2 = G.nodes[v][xCol]
            y2 = G.nodes[v][yCol]
            geom = LineString([(x1, y1), (x2, y2)])

        new_column_info = {
            'stnode':u,
            'endnode':v,
            'geometry':geom}

        for i in attr_list:
            try:
                new_column_info[i] = data[i]
            except:
                pass

        edges.append(new_column_info)

    edges_df = pd.DataFrame(edges)
    edges_df = edges_df[['stnode','endnode',*attr_list,'geometry']]
    edges_gdf = gpd.GeoDataFrame(edges_df, geometry = edges_df.geometry, crs = crs)

    return edges_gdf

def graph_nodes_intersecting_polygon(G, polygons, crs = None):

    """
    Function for generating GeoDataFrame from Graph. Note: ensure any GeoDataFrames are in the same projection before using function, or pass a crs

    :param G: a Graph object OR node geodataframe
    :param crs: a crs object of form {'init':'epsg:XXXX'}. If passed, matches both inputs to this crs.
    :returns: a list of the nodes intersecting the polygons
    """

    if type(G) == nx.classes.multidigraph.MultiDiGraph:
        graph_gdf = node_gdf_from_graph(G)

    elif type(G) == gpd.geodataframe.GeoDataFrame:
        graph_gdf = G

    else:
        raise ValueError('Expecting a graph or node geodataframe for G!')

    if type(polygons) != gpd.geodataframe.GeoDataFrame:
        raise ValueError('Expecting a geodataframe for polygon(s)!')

    if crs != None and graph_gdf.crs != crs:
            graph_gdf = graph_gdf.to_crs(crs)

    if crs != None and polygons.crs != crs:
            polygons = polygons.to_crs(crs)

    if polygons.crs != graph_gdf.crs:
        raise ValueError('crs mismatch detected! aborting process')

    intersecting_nodes = []
    for poly in polygons.geometry:

        def chck(x, poly):
            if poly.contains(x):
                return 1
            else:
                return 0

        graph_gdf['intersecting'] = graph_gdf['geometry'].apply(lambda x: chck(x, poly))
        intersecting_nodes.append(list(graph_gdf['node_ID'].loc[graph_gdf['intersecting'] == 1]))

    intersecting_nodes = [j for i in intersecting_nodes for j in i]
    unique_intersecting_nodes = list(set(intersecting_nodes))
    return unique_intersecting_nodes

def graph_edges_intersecting_polygon(G, polygons, mode, crs = None, fast = True):
    """
    Function for identifying edges of a graph that intersect polygon(s). Ensure any GeoDataFrames are in the same projection before using function, or pass a crs.

    :param G: a Graph object
    :param polygons: a GeoDataFrame containing one or more polygons
    :param mode: a string, either 'contains' or 'intersecting'
    :param crs: If passed, will reproject both polygons and graph edge gdf to this projection.
    :param fast: (default: True): we can cheaply test whether an edge intersects a polygon gdf by checking whether either the start or end nodes are within a polygon. If both are, then we return 'contained'; if at least one is, we can return 'intersects'. If we set fast to False, then we iterate through each geometry one at a time, and check to see whether the geometry object literally intersects the polygon geodataframe, one at a time. May be computationally intensive!
    :returns: a list of the edges intersecting the polygons
    """

    if type(G) == nx.classes.multidigraph.MultiDiGraph:
        node_graph_gdf = node_gdf_from_graph(G)
        edge_graph_gdf = edge_gdf_from_graph(G)
    else:
        raise ValueError('Expecting a graph for G!')

    if type(polygons) != gpd.geodataframe.GeoDataFrame:
        raise ValueError('Expecting a geodataframe for polygon(s)!')

    if crs != None and node_graph_gdf.crs != crs:
            node_graph_gdf = node_graph_gdf.to_crs(crs)

    if crs != None and polygons.crs != crs:
            polygons = polygons.to_crs(crs)

    if polygons.crs != node_graph_gdf.crs:
        raise ValueError('crs mismatch detected! aborting process')

    intersecting_nodes = graph_nodes_intersecting_polygon(node_graph_gdf, polygons, crs)

    if fast == True:

        if mode == 'contains':
            edge_graph_gdf = edge_graph_gdf.loc[(edge_graph_gdf.stnode.isin(intersecting_nodes)) &
                                     (edge_graph_gdf.endnode.isin(intersecting_nodes))]
        elif mode == 'intersects':
            edge_graph_gdf = edge_graph_gdf.loc[(edge_graph_gdf.stnode.isin(intersecting_nodes)) |
                                     (edge_graph_gdf.endnode.isin(intersecting_nodes))]
    elif fast == False:
        poly = unary_union(polygons.geometry)

        if mode == 'contains':
            edge_graph_gdf = edge_graph_gdf.loc[(edge_graph_gdf.within(poly))]

        elif mode == 'intersects':
            edge_graph_gdf = edge_graph_gdf.loc[(edge_graph_gdf.intersects(poly))]

    else:
        raise ValueError("'fast' requires a boolean input!!")

    return edge_graph_gdf

def sample_raster(G, tif_path, property_name = 'RasterValue'):
    """
    Function for attaching raster values to corresponding graph nodes. Ensure any GeoDataFrames / graphs are in the same projection before using function, or pass a crs

    :param G: a graph containing one or more nodes
    :param tif_path: a raster or path to a tif
    :param property_name: a property name for the value of the raster attached to the node
    :returns: a graph
    """

    import rasterio

    if type(G) == nx.classes.multidigraph.MultiDiGraph or type(G) == nx.classes.digraph.DiGraph:
        pass
    else:
        raise ValueError('Expecting a graph or geodataframe for G!')

    # generate dictionary of {node ID: point} pairs
    try:
        list_of_nodes = {}
        for u, data in G.nodes(data=True):
            list_of_nodes.update({u:(data['x'], data['y'])})
    except:
        raise ValueError('loading point geometry went wrong. Ensure node data dict includes x, y values!')

    # load raster
    try:
        dataset = rasterio.open(os.path.join(tif_path))
    except:
        raise ValueError('Expecting a path to a .tif file!')

    # create list of values, throw out nodes that don't intersect the bounds of the raster
    b = dataset.bounds
    datasetBoundary = box(b[0], b[1], b[2], b[3])
    selKeys = []
    selPts = []
    for key, pt in list_of_nodes.items():
        if Point(pt[0], pt[1]).intersects(datasetBoundary):
            selPts.append(pt)
            selKeys.append(key)
    raster_values = list(dataset.sample(selPts))
    raster_values = [x[0] for x in raster_values]

    # generate new dictionary of {node ID: raster values}
    ref = dict(zip(selKeys, raster_values))

    # load new values onto node data dictionary
    missedCnt = 0
    for u, data in G.nodes(data=True):
        try:
            data[property_name] = ref[u]
        except:
            missedCnt += 1
            logging.info("Could not add raster value to node %s" % u)
    logging.info("Number of original nodes: %s" % len(G.nodes))
    logging.info("Number of missed nodes in raster: %d" % missedCnt)
    logging.info("Number of nodes that intersected raster: %d" % len(selKeys))

    return G

def generate_isochrones(G, origins, thresh, weight = None, stacking = False):
    """
    Function for generating isochrones from one or more graph nodes. Ensure any GeoDataFrames / graphs are in the same projection before using function, or pass a crs

    :param G: a graph containing one or more nodes
    :param orgins: a list of node IDs that the isochrones are to be generated from
    :param thresh: The time threshold for the calculation of the isochrone
    :param weight: Name of edge weighting for calculating 'distances'. For isochrones, should be time expressed in seconds. Defaults to time expressed in seconds.
    :param stacking: If True, returns number of origins that can be reached from that node. If false, max = 1
    :returns: The original graph with a new data property for the nodes and edges included in the isochrone
    """

    if type(origins) == list and len(origins) >= 1:
        pass
    else:
        raise ValueError('Ensure isochrone centers (origins object) is a list containing at least one node ID!')

    ddict = list(G.nodes(data = True))[:1][0][1]

    if weight == None:
        if 'time' not in ddict.keys():
            raise ValueError('need "time" key in edge value dictionary!')
        else:
            weight = 'time'

    sub_graphs = []
    for node in origins:
        sub_graphs.append(nx.ego_graph(G, node, thresh, distance = weight))

    reachable_nodes = []
    for graph in sub_graphs:
        reachable_nodes.append(list(graph.nodes))

    reachable_nodes = [j for i in reachable_nodes for j in i]

    if stacking == False:

        reachable_nodes = set(reachable_nodes)

        for u, data in G.nodes(data=True):
            if u in reachable_nodes:
                data[thresh] = 1
            else:
                data[thresh] = 0

    elif stacking == True:

        reachable_nodes = Counter(reachable_nodes)

        for u, data in G.nodes(data=True):
            if u in reachable_nodes:
                data[thresh] = reachable_nodes[u]
            else:
                data[thresh] = 0
    else:
        raise ValueError('stacking must either be True or False!')

    return G

def make_iso_polys(G, origins, trip_times, edge_buff=10, node_buff=25, infill=False, weight = 'time', measure_crs = {'init':'epsg:4326'}):
    """
    Function for adding a time value to edge dictionaries

    :param G: a graph object
    :param origins: a list object of node IDs from which to generate an isochrone poly object
    :param trip_times: a list object containing the isochrone values
    :param edge_buff: the thickness with which to buffer included edges
    :param node_buff: the thickness with whcih to buffer included nodes
    :param infill: If True, will remove any holes in isochrones
    :param weight: The edge weight to use when appraising travel times.
    :param crs: measurement crs, object of form {'init':'epsg:XXXX'}
    """

    default_crs = {'init':'epsg:4326'}

    if type(origins) == list and len(origins) >= 1:
        pass
    else:
        raise ValueError('Ensure isochrone centers ("origins" object) is a list containing at least one node ID!')

    isochrone_polys, nodez, tt = [], [], []

    for trip_time in sorted(trip_times, reverse=True):

        for _node_ in origins:

            subgraph = nx.ego_graph(G, _node_, radius = trip_time, distance = weight)
            node_points = [Point((data['x'], data['y'])) for node, data in subgraph.nodes(data=True)]

            if len(node_points) > 1:

                nodes_gdf = gpd.GeoDataFrame({'id': subgraph.nodes()}, geometry=node_points, crs = default_crs)
                nodes_gdf = nodes_gdf.set_index('id')

                edge_lines = []
                for n_fr, n_to in subgraph.edges():
                    f = nodes_gdf.loc[n_fr].geometry
                    t = nodes_gdf.loc[n_to].geometry
                    edge_lines.append(LineString([f,t]))

                edge_gdf = gpd.GeoDataFrame({'geoms':edge_lines}, geometry = 'geoms', crs = default_crs)

                if measure_crs != None and nodes_gdf.crs != measure_crs:
                    nodes_gdf = nodes_gdf.to_crs(measure_crs)
                    edge_gdf = edge_gdf.to_crs(measure_crs)

                n = nodes_gdf.buffer(node_buff).geometry
                e = edge_gdf.buffer(edge_buff).geometry

                all_gs = list(n) + list(e)

                new_iso = gpd.GeoSeries(all_gs).unary_union

                # If desired, try and "fill in" surrounded
                # areas so that shapes will appear solid and blocks
                # won't have white space inside of them

                if infill:
                    new_iso = Polygon(new_iso.exterior)

                isochrone_polys.append(new_iso)
                tt.append(trip_time)
                nodez.append(str(_node_))
            else:
                pass

    gdf = gpd.GeoDataFrame({'geometry':isochrone_polys,'thresh':tt,'nodez':_node_}, crs = measure_crs, geometry = 'geometry')
    gdf = gdf.to_crs(default_crs)

    return gdf

def find_hwy_distances_by_class(G, distance_tag='length'):
    """
    Function for finding out the different highway classes in the graph and their respective lengths

    :param G: a graph object
    :param distance_tag: specifies which edge attribute represents length
    :returns: a dictionary that has each class and the total distance per class
    """

    if type(G) == nx.classes.multidigraph.MultiDiGraph or type(G) == nx.classes.digraph.DiGraph:
        pass
    else:
        raise ValueError('Expecting a graph or geodataframe for G!')

    G_adj = G.copy()

    class_list = []

    for u, v, data in G_adj.edges(data=True):
        #print(data['highway'])
        if type(data['highway']) == list:
                if data['highway'][0] not in class_list:
                    class_list.append(data['highway'][0])
        else:
            if data['highway'] not in class_list:
                class_list.append(data['highway'])
    
    class_dict = { i : 0 for i in class_list }

    for i in class_list:
        for u, v, data in G_adj.edges(data=True):
            if type(data['highway']) == list:
                if data['highway'][0] == i:
                    class_dict[i] += data[distance_tag]
            else:
                if data['highway'] == i:
                    class_dict[i] += data[distance_tag]

    return class_dict

def find_graph_avg_speed(G, distance_tag, time_tag):
    """
    Function for finding the average speed per km for the graph. It will sum up the total meters in the graph and the total time (in sec). \
    Then it will convert m/sec to km/hr. This function needs the 'convert_network_to_time' function to have run previously.
    
    :param G:
      a graph containing one or more nodes
    :param distance_tag:
      the key in the dictionary for the field currently containing a distance in meters
    :param time_tag:
      time to traverse the edge in seconds
    :returns:
      The average speed for the whole graph in km per hr
    """

    if type(G) == nx.classes.multidigraph.MultiDiGraph or type(G) == nx.classes.digraph.DiGraph:
        pass
    else:
        raise ValueError('Expecting a graph or geodataframe for G!')

    G_adj = G.copy()

    total_meters = 0
    total_sec = 0

    for u, v, data in G_adj.edges(data=True):

        total_meters = total_meters + data[distance_tag]
        total_sec = total_sec + data[time_tag]

    # perform conversion
    # ex. 5m/1sec = .005/.00027 = 18.51 kph
    avg_speed_kmph = (total_meters/1000)/(total_sec/3600)

    return avg_speed_kmph

def convert_network_to_time(G, distance_tag, graph_type = 'drive', road_col = 'highway', speed_dict = None, walk_speed = 4.5, factor = 1, default = None):
    """
    Function for adding a time value to edge dictionaries. Ensure any GeoDataFrames / graphs are in the same projection before using function, or pass a crs.

    DEFAULT SPEEDS:

               speed_dict = {
               'residential': 20,  # kmph
               'primary': 40, # kmph
               'primary_link':35,
               'motorway':50,
               'motorway_link': 45,
               'trunk': 40,
               'trunk_link':35,
               'secondary': 30,
               'secondary_link':25,
               'tertiary':30,
               'tertiary_link': 25,
               'unclassified':20
               }

    :param G: a graph containing one or more nodes
    :param distance_tag: the key in the dictionary for the field currently
               containing a distance in meters
    :param road_col: key for the road type in the edge data dictionary
    :param graph_type: set to either 'drive' or 'walk'. IF walk - will set time = walking time across all segment, using the supplied walk_speed. IF drive - will use a speed dictionary for each road type, or defaults as per the note below.
    :param speed_dict: speed dictionary to use. If not supplied, reverts to
               defaults
    :param walk_speed: specify a walkspeed in km/h
    :param factor: allows you to scale up / down distances if saved in a unit other than meters. Set to 1000 if length in km.
    :param default: if highway type not in the speed_dict, use this road class as an in-fill value for time.
    :returns: The original graph with a new data property for the edges called 'time'
    """

    if type(G) == nx.classes.multidigraph.MultiDiGraph or type(G) == nx.classes.digraph.DiGraph:
        pass
    else:
        raise ValueError('Expecting a graph or geodataframe for G!')

    G_adj = G.copy()

    for u, v, data in G_adj.edges(data=True):

        orig_len = data[distance_tag] * factor

        # Note that this is a MultiDiGraph so there could
        # be multiple indices here, I naively assume this is not
        # the case
        data['length'] = orig_len

        # get appropriate speed limit
        if graph_type == 'walk':
            speed = walk_speed

        elif graph_type == 'drive':

            if speed_dict == None:
                speed_dict = {
                'residential': 20,  # kmph
                'primary': 40, # kmph
                'primary_link':35,
                'motorway':50,
                'motorway_link': 45,
                'trunk': 40,
                'trunk_link':35,
                'secondary': 30,
                'secondary_link':25,
                'tertiary':30,
                'tertiary_link': 25,
                'unclassified':20
                }

            highwayclass = data[road_col]

            if type(highwayclass) == list:
                highwayclass = highwayclass[0]

            if highwayclass in speed_dict.keys():
                speed = speed_dict[highwayclass]
            else:
                if default == None:
                    speed = 20
                else:
                    speed = speed_dict[default]

        else:
            raise ValueError('Expecting either a graph_type of "walk" or "drive"!')

        # perform conversion
        kmph = (orig_len / 1000) / speed
        in_seconds = kmph * 60 * 60
        data['time'] = in_seconds

        # And state the mode, too
        data['mode'] = graph_type

    return G_adj

def example_edge(G, n=1):
    """
    Prints out an example edge

    :param G: a graph object
    :param n: n - number of edges to print
    """
    i = list(G.edges(data = True))[:n]
    for j in i:
        print(j)

def example_node(G, n=1):
    """
    Prints out an example node

    :param G: a graph object
    :param n: number of nodes to print
    """

    i = list(G.nodes(data = True))[:n]
    for j in i:
        print(j)

def calculate_OD(G, origins, destinations, fail_value, weight = 'time', weighted_origins = False):
    """
    Function for generating an origin: destination matrix

    :param G: a graph containing one or more nodes
    :param fail_value: the value to return if the trip cannot be completed (implies some sort of disruption / disconnected nodes)
    :param origins: a list of the node IDs to treat as origins points
    :param destinations: a list of the node IDs to treat as destinations
    :param weight: use edge weight of 'time' unless otherwise specified
    :param weighted_origins: equals 'true' if the origins have weights. If so, the input to 'origins' must be dictionary instead of a list, where the keys are the origin IDs and the values are the weighted demands.
    :returns: a numpy matrix of format OD[o][d] = shortest time possible
    """
    
    if weighted_origins == True:
        print('weighted_origins equals true')
        OD = np.zeros((len(origins), len(destinations)))
        #dictionary key length
        o = 0
        #loop through dictionary
        for key,value in origins.items():
            origin = key
            for d in range(0,len(destinations)):
                destination = destinations[d]
                #find the shortest distance between the origin and destination
                distance = nx.dijkstra_path_length(G, origin, destination, weight = weight)
                # calculate weighted distance
                weighted_distance = distance * float(value)
                OD[o][d] = weighted_distance
            o += 1

    else:
        flip = 0
        if len(origins) > len(destinations):
            flip = 1
            o_2 = destinations
            destinations = origins
            origins = o_2

        #origins will be number or rows, destinations will be number of columns
        OD = np.zeros((len(origins), len(destinations)))

        for o in range(0, len(origins)):
            origin = origins[o]
            results_dict = nx.single_source_dijkstra_path_length(G, origin, cutoff = None, weight = weight)

            for d in range(0, len(destinations)):
                destination = destinations[d]
                if destination in results_dict.keys():
                    OD[o][d] = results_dict[destination]
                else:
                    OD[o][d] = fail_value

        if flip == 1:
            OD = np.transpose(OD)

    return OD

def disrupt_network(G, property, thresh, fail_value):
    """
    Function for disrupting a graph given a threshold value against a node's value. Any edges which bind to broken nodes have their 'time' property set to fail_value

    :param G: REQUIRED a graph containing one or more nodes and one or more edges
    :param property: the element in the data dictionary for the edges to test
    :param thresh: values of data[property] above this value are disrupted
    :param fail_value: The data['time'] property is set to this value to simulate the removal of the edge
    :returns: a modified graph with the edited 'time' attribute
    """
    G_copy = G.copy()

    broken_nodes = []

    for u, data in G_copy.nodes(data = True):

        if data[property] > thresh:

            broken_nodes.append(u)

    print('nodes disrupted: %s' % len(broken_nodes))
    i = 0
    for u, v, data in G_copy.edges(data = True):

        if u in broken_nodes or v in broken_nodes:

            data['time'] = fail_value
            i+=1

    print('edges disrupted: %s' % i)
    return G_copy

def randomly_disrupt_network(G, edge_frac, fail_value):
    """
    Function for randomly disurpting a network. NOTE: requires the graph to have an 'edge_id' value in the edge data dictionary. This DOES NOT have to be unique.

    :param G: a graph containing one or more nodes and one or more edges
    :param edge_frac: the percentage of edges to destroy. Integer rather than decimal, e.g. 5 = 5% of edges
    :param fail_value: the data['time'] property is set to this value to simulate the removal of the edge      
    :returns: a modified graph with the edited 'time' attribute the list of edge IDs randomly chosen for destruction
    """

    edgeid = []

    for u,v, data in G.edges(data = True):
        edgeid.append(data['edge_id'])

    num_to_destroy = math.floor(len(edgeid) / 2 * (edge_frac / 100))

    destroy_list = list(np.random.randint(low = 0, high = max(edgeid), size = [num_to_destroy]))

    G_adj = G.copy()

    for u, v, data in G_adj.edges(data = True):
        if data['edge_id'] in destroy_list:
            data['time'] = fail_value

    return G_adj, destroy_list

def gravity_demand(G, origins, destinations, weight, maxtrips = 100, dist_decay = 1, fail_value = 99999999999):
    """
    Function for generating a gravity-model based demand matrix. Note: 1 trip will always be returned between an origin and a destination, even if weighting would otherewise be 0.
    :param origins: a list of node IDs. Must be in G.
    :param destinations: a list of node IDs Must be in G.
    :param weight: the gravity weighting of the nodes in the model, e.g. population
    :param fail_value: the data['time'] property is set to this value to simulate the removal of the edge
    :param maxtrips: normalize the number of trips in the resultant function to this number of trip_times
    :param dist_decay: parameter controlling the aggresion of discounting based on distance
    :returns: a numpy array describing the demand between o and d in terms of number of trips
    """

    maxtrips = 100
    dist_decay = 1

    demand = np.zeros((len(origins), len(destinations)))

    shortest_time = Calculate_OD(G, origins, destinations, fail_value)

    for o in range(0, len(origins)):
        for d in range(0, len(destinations)):
            if origins == destinations and o == d:
                demand[o][d] = 0
            else:
                normalized_dist = shortest_time[o][d] / shortest_time.max()
                demand[o][d] = (
                (G.node[origins[o]][weight] *
                G.node[destinations[d]][weight]) *
                np.exp(-1 * dist_decay * normalized_dist)
                )

    demand = ((demand / demand.max()) * maxtrips)
    demand = np.ceil(demand).astype(int)
    return demand

def unbundle_geometry(c):
    """
    Function for unbundling complex geometric objects. Note: shapely MultiLineString objects quickly get complicated. They may not show up when you plot them in QGIS. This function aims to make a .csv 'plottable'

    :param c: any object. This helper function is usually applied in lambda format against a pandas / geopandas dataframe. The idea is to try to return more simple versions of complex geometries for LineString and MultiLineString type objects.
    :returns: an unbundled geometry value that can be plotted.
    """

    if type(c) == list:
        objs = []
        for i in c:
            if type(i) == str:
                J = loads(i)
                if type(J) == LineString:
                    objs.append(J)
                if type(J) == MultiLineString:
                    for j in J:
                        objs.append(j)
            elif type(i) == MultiLineString:
                for j in i:
                    objs.append(j)
            elif type(i) == LineString:
                objs.append(i)
            else:
                pass
            mls = MultiLineString(objs)
            ls = linemerge(mls)
        return ls
    elif type(c) == str:
        return loads(c)
    else:
        return c

def save(G, savename, wpath, pickle = True, edges = True, nodes = True):
    """
    function used to save a graph object in a variety of handy formats

    :param G: a graph object
    :param savename: the filename, WITHOUT extension
    :param wpath: the write path for where the user wants the files saved
    :param pickle: if set to false, will not save a pickle of the graph
    :param edges: if set to false, will not save an edge gdf
    :param nodes: if set to false, will not save a node gdf
    """

    if nodes == True:
        new_node_gdf = node_gdf_from_graph(G)
        new_node_gdf.to_csv(os.path.join(wpath, '%s_nodes.csv' % savename))
    if edges == True:
        new_edge_gdf = edge_gdf_from_graph(G)
        new_edge_gdf.to_csv(os.path.join(wpath, '%s_edges.csv' % savename))
    if pickle == True:
        nx.write_gpickle(G, os.path.join(wpath, '%s.pickle' % savename))

def add_missing_reflected_edges(G):
    """
    function for adding any missing reflected edges - makes all edges bidirectional. This is essential for routing with simplified graphs

    :param G: a graph object
    """
    unique_edges = []
    missing_edges = []

    for u, v in G.edges(data = False):
        unique_edges.append((u,v))
    for u, v, data in G.edges(data = True):
        if (v, u) not in unique_edges:
            missing_edges.append((v,u,data))
    G2 = G.copy()
    G2.add_edges_from(missing_edges)
    print(G2.number_of_edges())
    return G2

def remove_duplicate_edges(G, max_ratio = 1.5):
    """
    function for deleting duplicated edges - where there is more than one edge connecting a node pair. USE WITH CAUTION - will change both topological relationships and node maps
    :param G: a graph object
    :param max_ratio: most of the time we see duplicate edges that are clones of each other. Sometimes, however, there are valid duplicates. These occur if multiple roads connect two junctions uniquely and without interruption - e.g. two roads running either side of a lake which meet at either end. The idea here is that valid 'duplicate edges' will have geometries of materially different length. Hence, we include a ratio - defaulting to 1.5 - beyond which we are sure the duplicates are valid edges, and will not be deleted.
    """

    G2 = G.copy()
    uniques = []
    deletes = []
    for u, v, data in G2.edges(data = True):
        if (u,v) not in uniques:
            uniques.append((v,u))
            t = G2.number_of_edges(u, v)
            lengths = []
            for i in range(0,t):
                lengths.append(G2.edges[u,v,i]['length'])
            if max(lengths) / min(lengths) >= max_ratio:
                pass
            else:
                deletes.append((u,v))

    for d in deletes:
        G2.remove_edge(d[0],d[1])
    print(G2.number_of_edges())
    return G2

def convert_to_MultiDiGraph(G):
    """
    takes any graph object, loads it into a MultiDiGraph type Networkx object
    :param G: a graph object
    """
    a = nx.MultiDiGraph()

    node_bunch = []
    for u, data in G.nodes(data = True):
        node_bunch.append((u,data))

    a.add_nodes_from(node_bunch)

    edge_bunch = []
    for u, v, data in G.edges(data = True):
        if 'Wkt' in data.keys():
            data['Wkt'] = str(data['Wkt'])
        edge_bunch.append((u,v,data))

    a.add_edges_from(edge_bunch)
    return a

#### NETWORK SIMPLIFICATION ####

def simplify_junctions(G, measure_crs, in_crs = {'init': 'epsg:4326'}, thresh = 25):
    """
    simplifies topology of networks by simplifying node clusters into single nodes.

    :param G: a graph object
    :param measure_crs: the crs to make the measurements inself.
    :param in_crs: the current crs of the graph's geometry properties. By default, assumes WGS 84 (epsg 4326)
    :param thresh: the threshold distance in which to simplify junctions. By default, assumes 25 meters
    """

    G2 = G.copy()

    gdfnodes = node_gdf_from_graph(G2)
    gdfnodes_proj_buffer = gdfnodes.to_crs(measure_crs)
    gdfnodes_proj_buffer = gdfnodes_proj_buffer.buffer(thresh)
    juncs_gdf = gpd.GeoDataFrame(pd.DataFrame({'geometry':unary_union(gdfnodes_proj_buffer)}), crs = measure_crs, geometry = 'geometry')
    juncs_gdf['area'] = juncs_gdf.area

    juncs_gdf_2 = juncs_gdf.copy()
    juncs_gdf_2 = juncs_gdf_2.loc[juncs_gdf_2.area > int(juncs_gdf.area.min() + 1)]
    juncs_gdf = juncs_gdf_2
    juncs_gdf = juncs_gdf.reset_index()
    juncs_gdf['obj_ID'] = juncs_gdf.index
    juncs_gdf['obj_ID'] = 'new_obj_'+juncs_gdf['obj_ID'].astype(str)

    juncs_gdf_unproj = juncs_gdf.to_crs(in_crs)
    juncs_gdf_unproj['centroid'] = juncs_gdf_unproj.centroid
    juncs_gdf_bound = gpd.sjoin(juncs_gdf_unproj, gdfnodes, how='left', op='intersects', lsuffix='left', rsuffix='right')
    juncs_gdf_bound = juncs_gdf_bound[['obj_ID','centroid','node_ID']]

    node_map = juncs_gdf_bound[['obj_ID','node_ID']]
    node_map = node_map.set_index('node_ID')
    node_dict = node_map['obj_ID'].to_dict()
    nodes_to_be_destroyed = list(node_dict.keys())

    centroid_map = juncs_gdf_bound[['obj_ID','centroid']]
    centroid_map = centroid_map.set_index('obj_ID')
    centroid_dict = centroid_map['centroid'].to_dict()
    new_node_IDs = list(centroid_dict.keys())

    # Add the new centroids of the junction areas as new nodes
    new_nodes = []
    for i in new_node_IDs:
        new_nodes.append((i, {'x':centroid_dict[i].x, 'y':centroid_dict[i].y}))
    G2.add_nodes_from(new_nodes)

    # modify edges - delete those where both u and v are to be removed, edit the others
    edges_to_be_destroyed = []
    new_edges = []

    for u, v, data in G2.edges(data = True):

        if type(data['Wkt']) == LineString:
            l = data['Wkt']
        else:
            l = loads(data['Wkt'])

        line_to_be_edited = l.coords

        if u in nodes_to_be_destroyed and v in nodes_to_be_destroyed:
            if node_dict[u] == node_dict[v]:
                edges_to_be_destroyed.append((u,v))

            else:
                new_ID_u = node_dict[u]
                new_point_u = centroid_dict[new_ID_u]
                new_ID_v = node_dict[v]
                new_point_v = centroid_dict[new_ID_v]

                if len(line_to_be_edited) > 2:
                    data['Wkt'] = LineString([new_point_u, *line_to_be_edited[1:-1], new_point_v])
                else:
                    data['Wkt'] = LineString([new_point_u, new_point_v])
                data['Type'] = 'dual_destruction'

                new_edges.append((new_ID_u,new_ID_v,data))
                edges_to_be_destroyed.append((u,v))

        else:

            if u in nodes_to_be_destroyed:
                new_ID_u = node_dict[u]
                u = new_ID_u

                new_point = centroid_dict[new_ID_u]
                coords = [new_point, *line_to_be_edited[1:]]
                data['Wkt'] = LineString(coords)
                data['Type'] = 'origin_destruction'

                new_edges.append((new_ID_u,v,data))
                edges_to_be_destroyed.append((u,v))

            elif v in nodes_to_be_destroyed:
                new_ID_v = node_dict[v]
                v = new_ID_v

                new_point = centroid_dict[new_ID_v]
                coords = [*line_to_be_edited[:-1], new_point]
                data['Wkt'] = LineString(coords)
                data['Type'] = 'destination_destruction'

                new_edges.append((u,new_ID_v,data))
                edges_to_be_destroyed.append((u,v))

            else:
                data['Type'] = 'legitimate'
                pass

    # remove old edges that connected redundant nodes to each other / edges where geometry needed to be changed
    G2.remove_edges_from(edges_to_be_destroyed)

    # ... and add any corrected / new edges
    G2.add_edges_from(new_edges)

    # remove now redundant nodes
    G2.remove_nodes_from(nodes_to_be_destroyed)

    print(G2.number_of_edges())

    return G2

def custom_simplify(G, strict=True):
    """
    Simplify a graph's topology by removing all nodes that are not intersections or dead-ends. Create an edge directly between the end points that encapsulate them, but retain the geometry of the original edges, saved as attribute in new edge.

    :param G: networkx multidigraph
    :param bool strict: if False, allow nodes to be end points even if they fail all other rules but have edges with different OSM IDs
    :returns: networkx multidigraph
    """

    def get_paths_to_simplify(G, strict=True):

        """
        Create a list of all the paths to be simplified between endpoint nodes.

        The path is ordered from the first endpoint, through the interstitial nodes,
        to the second endpoint. If your street network is in a rural area with many
        interstitial nodes between true edge endpoints, you may want to increase
        your system's recursion limit to avoid recursion errors.

        Parameters
        ----------
        G : networkx multidigraph
        strict : bool
            if False, allow nodes to be end points even if they fail all other rules
            but have edges with different OSM IDs

        Returns
        -------
        paths_to_simplify : list
        """

        # first identify all the nodes that are endpoints
        start_time = time.time()
        endpoints = set([node for node in G.nodes() if is_endpoint(G, node, strict=strict)])

        start_time = time.time()
        paths_to_simplify = []

        # for each endpoint node, look at each of its successor nodes
        for node in endpoints:
            for successor in G.successors(node):
                if successor not in endpoints:
                    # if the successor is not an endpoint, build a path from the
                    # endpoint node to the next endpoint node
                    try:
                        path = build_path(G, successor, endpoints, path=[node, successor])
                        paths_to_simplify.append(path)
                    except RuntimeError:
                        # recursion errors occur if some connected component is a
                        # self-contained ring in which all nodes are not end points.
                        # could also occur in extremely long street segments (eg, in
                        # rural areas) with too many nodes between true endpoints.
                        # handle it by just ignoring that component and letting its
                        # topology remain intact (this should be a rare occurrence)
                        # RuntimeError is what Python <3.5 will throw, Py3.5+ throws
                        # RecursionError but it is a subtype of RuntimeError so it
                        # still gets handled
                        pass

        return paths_to_simplify

    def is_endpoint(G, node, strict=True):
        """
        Return True if the node is a "real" endpoint of an edge in the network, \
        otherwise False. OSM data includes lots of nodes that exist only as points \
        to help streets bend around curves. An end point is a node that either: \
        1) is its own neighbor, ie, it self-loops. \
        2) or, has no incoming edges or no outgoing edges, ie, all its incident \
            edges point inward or all its incident edges point outward. \
        3) or, it does not have exactly two neighbors and degree of 2 or 4. \
        4) or, if strict mode is false, if its edges have different OSM IDs. \

        Parameters
        ----------
        G : networkx multidigraph

        node : int
            the node to examine
        strict : bool
            if False, allow nodes to be end points even if they fail all other rules \
            but have edges with different OSM IDs

        Returns
        -------
        bool
        """

        neighbors = set(list(G.predecessors(node)) + list(G.successors(node)))
        n = len(neighbors)
        d = G.degree(node)

        if node in neighbors:
            # if the node appears in its list of neighbors, it self-loops. this is
            # always an endpoint.
            return 'node in neighbours'

        # if node has no incoming edges or no outgoing edges, it must be an endpoint
        #elif G.out_degree(node)==0 or G.in_degree(node)==0:
            #return 'no in or out'

        elif not (n==2 and (d==2 or d==4)):
            # else, if it does NOT have 2 neighbors AND either 2 or 4 directed
            # edges, it is an endpoint. either it has 1 or 3+ neighbors, in which
            # case it is a dead-end or an intersection of multiple streets or it has
            # 2 neighbors but 3 degree (indicating a change from oneway to twoway)
            # or more than 4 degree (indicating a parallel edge) and thus is an
            # endpoint
            return 'condition 3'

        elif not strict:
            # non-strict mode
            osmids = []

            # add all the edge OSM IDs for incoming edges
            for u in G.predecessors(node):
                for key in G[u][node]:
                    osmids.append(G.edges[u, node, key]['osmid'])

            # add all the edge OSM IDs for outgoing edges
            for v in G.successors(node):
                for key in G[node][v]:
                    osmids.append(G.edges[node, v, key]['osmid'])

            # if there is more than 1 OSM ID in the list of edge OSM IDs then it is
            # an endpoint, if not, it isn't
            return len(set(osmids)) > 1

        else:
            # if none of the preceding rules returned true, then it is not an endpoint
            return False

    def build_path(G, node, endpoints, path):
        """
        Recursively build a path of nodes until you hit an endpoint node.

        :param G: networkx multidigraph
        :param int node: the current node to start from
        :param set endpoints: the set of all nodes in the graph that are endpoints
        :param list path: the list of nodes in order in the path so far
        :returns list: paths_to_simplify
        """

        # for each successor in the passed-in node
        for successor in G.successors(node):
            if successor not in path:
                # if this successor is already in the path, ignore it, otherwise add
                # it to the path
                path.append(successor)
                if successor not in endpoints:
                    # if this successor is not an endpoint, recursively call
                    # build_path until you find an endpoint
                    path = build_path(G, successor, endpoints, path)
                else:
                    # if this successor is an endpoint, we've completed the path,
                    # so return it
                    return path

        if (path[-1] not in endpoints) and (path[0] in G.successors(path[-1])):
            # if the end of the path is not actually an endpoint and the path's
            # first node is a successor of the path's final node, then this is
            # actually a self loop, so add path's first node to end of path to
            # close it
            path.append(path[0])

        return path

    ## MAIN PROCESS FOR CUSTOM SIMPLIFY ##

    G = G.copy()

    if type(G) != nx.classes.multidigraph.MultiDiGraph:
        G = ConvertToMultiDiGraph(G)
    initial_node_count = len(list(G.nodes()))
    initial_edge_count = len(list(G.edges()))
    all_nodes_to_remove = []
    all_edges_to_add = []

    # construct a list of all the paths that need to be simplified
    paths = get_paths_to_simplify(G, strict=strict)

    start_time = time.time()
    for path in paths:

        # add the interstitial edges we're removing to a list so we can retain
        # their spatial geometry
        edge_attributes = {}
        for u, v in zip(path[:-1], path[1:]):

            # there shouldn't be multiple edges between interstitial nodes
            if not G.number_of_edges(u, v) == 1:
                pass
            # the only element in this list as long as above check is True
            # (MultiGraphs use keys (the 0 here), indexed with ints from 0 and
            # up)
            edge = G.edges[u, v, 0]
            for key in edge:
                if key in edge_attributes:
                    # if this key already exists in the dict, append it to the
                    # value list
                    edge_attributes[key].append(edge[key])
                else:
                    # if this key doesn't already exist, set the value to a list
                    # containing the one value
                    edge_attributes[key] = [edge[key]]

        for key in edge_attributes:
            # don't touch the length attribute, we'll sum it at the end
            if key == 'Wkt':
                edge_attributes['Wkt'] = list(edge_attributes['Wkt'])
            elif key != 'length' and key != 'Wkt':      # if len(set(edge_attributes[key])) == 1 and not key == 'length':
                # if there's only 1 unique value in this attribute list,
                # consolidate it to the single value (the zero-th)
                edge_attributes[key] = edge_attributes[key][0]
            elif not key == 'length':
                # otherwise, if there are multiple values, keep one of each value
                edge_attributes[key] = list(set(edge_attributes[key]))

        # construct the geometry and sum the lengths of the segments
        edge_attributes['geometry'] = LineString([Point((G.nodes[node]['x'], G.nodes[node]['y'])) for node in path])
        edge_attributes['length'] = sum(edge_attributes['length'])

        # add the nodes and edges to their lists for processing at the end
        all_nodes_to_remove.extend(path[1:-1])
        all_edges_to_add.append({'origin':path[0],
                                 'destination':path[-1],
                                 'attr_dict':edge_attributes})

    # for each edge to add in the list we assembled, create a new edge between
    # the origin and destination
    for edge in all_edges_to_add:
        G.add_edge(edge['origin'], edge['destination'], **edge['attr_dict'])

    # finally remove all the interstitial nodes between the new edges
    G.remove_nodes_from(set(all_nodes_to_remove))

    msg = 'Simplified graph (from {:,} to {:,} nodes and from {:,} to {:,} edges) in {:,.2f} seconds'
    return G

def salt_long_lines(G, source, target, thresh = 5000, factor = 1, attr_list = None):
    print('WARNING: "factor behavior has changed! now divides rather than multiplies. This change brings gn.salt_long_lines into line with gn.convert_network_to_time" ')
    """
    Adds in new nodes to edges greater than a given length

    :param G: a graph object
    :param source: crs object in format 'epsg:4326'
    :param target: crs object in format 'epsg:32638'
    :param thresh: distance in metres after which to break edges.
    :param factor: edge lengths can be returned in units other than metres by specifying a numerical multiplication factor
    :param attr_dict: list of attributes to be saved onto new edges.
    """

    def cut(line, distance):
        # Cuts a line in two at a distance from its starting point
        if distance <= 0.0 or distance >= line.length:
            return [LineString(line)]

        coords = list(line.coords)
        for i, p in enumerate(coords):
            pd = line.project(Point(p))
            if pd == distance:
                return [LineString(coords[:i+1]),LineString(coords[i:])]
            if pd > distance:
                cp = line.interpolate(distance)
                return [LineString(coords[:i] + [(cp.x, cp.y)]),LineString([(cp.x, cp.y)] + coords[i:])]

    G2 = G.copy()

    # define transforms for exchanging between source and target projections

    project_WGS_UTM = partial(
                pyproj.transform,
                pyproj.Proj(init=source),
                pyproj.Proj(init=target))

    project_UTM_WGS = partial(
                pyproj.transform,
                pyproj.Proj(init=target),
                pyproj.Proj(init=source))

    long_edges, long_edge_IDs, unique_long_edges, new_nodes, new_edges = [], [], [], [], []

    # Identify long edges
    for u, v, data in G2.edges(data = True):

        # load geometry
        if type(data['Wkt']) == str:
            WGS_geom = loads(data['Wkt'])
        else:
            WGS_geom = unbundle_geometry(data['Wkt'])
        UTM_geom = transform(project_WGS_UTM, WGS_geom)

        # test geomtry length
        if UTM_geom.length > thresh:
            long_edges.append((u, v, data))
            long_edge_IDs.append((u,v))
            if (v, u) in long_edge_IDs:
                pass
            else:
                unique_long_edges.append((u, v, data))

    print('Identified %d unique edge(s) longer than %d. \nBeginning new node creation...' % (len(unique_long_edges), thresh))

    # iterate through one long edge for each bidirectional long edge pair

    j,o = 1, 0

    for u, v, data in unique_long_edges:

        # load geometry of long edge
        if type(data['Wkt']) == str:
            WGS_geom = loads(data['Wkt'])
        else:
            WGS_geom = unbundle_geometry(data['Wkt'])

        if WGS_geom.type == 'MultiLineString':
            WGS_geom = linemerge(WGS_geom)

        UTM_geom = transform(project_WGS_UTM, WGS_geom)

        # flip u and v if Linestring running from v to u, coordinate-wise
        u_x_cond = round(WGS_geom.coords[0][0], 6) == round(G.nodes()[u]['x'], 6)
        u_y_cond = round(WGS_geom.coords[0][1], 6) == round(G.nodes()[u]['y'], 6)

        v_x_cond = round(WGS_geom.coords[0][0], 6) == round(G.nodes()[v]['x'], 6)
        v_y_cond = round(WGS_geom.coords[0][1], 6) == round(G.nodes()[v]['y'], 6)

        if u_x_cond and u_y_cond:
            pass
        elif v_x_cond and v_y_cond:
            u, v = v, u
        else:
            print('ERROR!')

        # calculate number of new nodes to add along length
        number_of_new_points = UTM_geom.length / thresh

        # for each new node
        for i in range(0, int(number_of_new_points+1)):

            ## GENERATE NEW NODES ##

            cur_dist = (thresh * (i+1))

            # generate new geometry along line
            new_point = UTM_geom.interpolate(cur_dist)

            new_point_WGS = transform(project_UTM_WGS, new_point)

            node_data = {'geometry': new_point_WGS,
                        'x' : new_point_WGS.x,
                        'y': new_point_WGS.y}

            new_node_ID = str(u)+'_'+str(i+j)+'_'+str(o)

            # generate a new node as long as we aren't the final node
            if i < int(number_of_new_points):
                new_nodes.append((new_node_ID, node_data))

            ## GENERATE NEW EDGES ##
            try:
                # define geometry to be cutting (iterative)
                if i == 0:
                    geom_to_split = UTM_geom

                else:
                    geom_to_split = result[1]

                # cut geometry. result[0] is the section cut off, result[1] is remainder
                result = cut(geom_to_split, (thresh))

                t_geom = transform(project_UTM_WGS, result[0])

                edge_data = {'Wkt' : t_geom,
                            'length' : (int(result[0].length) / factor),
                            }

                if attr_list != None:
                    for attr in attr_list:
                        edge_data[attr] = data[attr]

                if i == 0:
                    prev_node_ID = u

                if i == int(number_of_new_points):
                    new_node_ID = v

                # append resulting edges to a list of new edges, bidirectional.
                new_edges.append((prev_node_ID,new_node_ID,edge_data))
                new_edges.append((new_node_ID,prev_node_ID,edge_data))

                o += 1

                prev_node_ID = new_node_ID
            except:
                pass

        j+=1

    # add new nodes and edges
    G2.add_nodes_from(new_nodes)
    G2.add_edges_from(new_edges)

    # remove the too-long edges
    for d in long_edges:
        G2.remove_edge(d[0],d[1])

    print('%d new edges added and %d removed to bring total edges to %d' % (len(new_edges),len(long_edges),G2.number_of_edges()))
    print('%d new nodes added to bring total nodes to %d' % (len(new_nodes),G2.number_of_nodes()))

    return G2

def pandana_snap(G, point_gdf, source_crs = 'epsg:4326', target_crs = 'epsg:4326', 
                    add_dist_to_node_col = True):
    """
    snaps points to a graph at very high speed
    :param G: a graph object
    :param point_gdf: a geodataframe of points, in the same source crs as the geometry of the graph object
    :param source_crs: crs object in format 'epsg:32638'
    :param target_crs: crs object in format 'epsg:32638'
    :param add_dist_to_node_col: return distance in metres to nearest node
    """

    in_df = point_gdf.copy()
    node_gdf = node_gdf_from_graph(G)

    if add_dist_to_node_col is True:

        project_WGS_UTM = partial(
                    pyproj.transform,
                    pyproj.Proj(init=source_crs),
                    pyproj.Proj(init=target_crs))

        in_df['Proj_geometry'] = in_df.apply(lambda x: transform(project_WGS_UTM, x.geometry), axis = 1)
        in_df = in_df.set_geometry('Proj_geometry')
        in_df['x'] = in_df.Proj_geometry.x
        in_df['y'] = in_df.Proj_geometry.y

        node_gdf['Proj_geometry'] = node_gdf.apply(lambda x: transform(project_WGS_UTM, x.geometry), axis = 1)
        node_gdf = node_gdf.set_geometry('Proj_geometry')
        node_gdf['x'] = node_gdf.Proj_geometry.x
        node_gdf['y'] = node_gdf.Proj_geometry.y

        G_tree = spatial.KDTree(node_gdf[['x','y']].as_matrix())

        distances, indices = G_tree.query(in_df[['x','y']].as_matrix())

        in_df['NN'] = list(node_gdf['node_ID'].iloc[indices])
        in_df['NN_dist'] = distances
        in_df = in_df.drop(['x','y','Proj_geometry'], axis = 1)

    else:
        in_df['x'] = in_df.geometry.x
        in_df['y'] = in_df.geometry.y
        G_tree = spatial.KDTree(node_gdf[['x','y']].as_matrix())

        distances, indices = G_tree.query(in_df[['x','y']].as_matrix())

        in_df['NN'] = list(node_gdf['node_ID'].iloc[indices])

    return in_df

def pandana_snap_points(source_gdf, target_gdf, source_crs = 'epsg:4326', target_crs = 'epsg:4326', add_dist_to_node_col = True):
    """
    snaps points to another GeoDataFrame at very high speed

    :param source_gdf: a geodataframe of points, in the same source crs as the geometry of the target_gdf
    :param target_gdf: a geodataframe of points, in the same source crs as the geometry of the source_gdf
    :param source_gdf: a geodataframe of points, in the same source crs as the geometry of the source_gdf
    :param source_crs: crs object in format 'epsg:32638'
    :param target_crs: crs object in format 'epsg:32638'
    :param add_dist_to_node_col: return distance in metres to nearest node
    """

    source_gdf = source_gdf.copy()
    target_gdf = target_gdf.copy()
    target_gdf['ID'] = target_gdf.index

    if add_dist_to_node_col is True:

        project_WGS_UTM = partial(
                    pyproj.transform,
                    pyproj.Proj(init=source_crs),
                    pyproj.Proj(init=target_crs))

        target_gdf['P'] = target_gdf.apply(lambda x: transform(project_WGS_UTM, x.geometry), axis = 1)
        target_gdf = target_gdf.set_geometry('P')
        target_gdf['x'] = target_gdf.P.x
        target_gdf['y'] = target_gdf.P.y

        source_gdf['P'] = source_gdf.apply(lambda x: transform(project_WGS_UTM, x.geometry), axis = 1)
        source_gdf = source_gdf.set_geometry('P')
        source_gdf['x'] = source_gdf.P.x
        source_gdf['y'] = source_gdf.P.y

        G_tree = spatial.KDTree(target_gdf[['x','y']].as_matrix())

        distances, indices = G_tree.query(source_gdf[['x','y']].as_matrix())

        source_gdf['NN'] = list(target_gdf['ID'].iloc[indices])

        source_gdf['NN_dist'] = distances

        source_gdf = source_gdf.drop(['x','y','P'], axis = 1)

    else:

        target_gdf['x'] = target_gdf.geometry.x
        target_gdf['y'] = target_gdf.geometry.y

        G_tree = spatial.KDTree(target_gdf[['x','y']].as_matrix())

        distances, indices = G_tree.query(source_gdf[['x','y']].as_matrix())

        source_gdf['NN'] = list(target_gdf['ID'].iloc[indices])

    return source_gdf

def join_networks(base_net, new_net, measure_crs, thresh = 500):
    """
    joins two networks together within a binding threshold

    :param base_net: a base network object (nx.MultiDiGraph)
    :param new_net: the network to add on to the base (nx.MultiDiGraph)
    :param measure_crs: the crs number of the measurement (epsg code)
    :param thresh: binding threshold - unit of the crs - default 500m
    """
    G_copy = base_net.copy()
    join_nodes_df = pandana_snap(G_copy,
                         node_gdf_from_graph(new_net),
                         source_crs = 'epsg:4326',
                         target_crs = 'epsg:%s' % measure_crs,
                         add_dist_to_node_col = True)

    join_nodes_df = join_nodes_df.sort_values(by = 'NN_dist', ascending = True)
    join_nodes_df = join_nodes_df.loc[join_nodes_df.NN_dist < thresh]

    nodes_to_add, edges_to_add = [],[]

    for u, data in new_net.nodes(data = True):
        u = 'add_net_%s' % u
        nodes_to_add.append((u,data))

    for u,v, data in new_net.edges(data = True):
        u = 'add_net_%s' % u
        v = 'add_net_%s' % v
        edges_to_add.append((u,v,data))

    gdf_base = node_gdf_from_graph(base_net)
    gdf_base = gdf_base.set_index('node_ID')

    for index, row in join_nodes_df.iterrows():
        u = 'add_net_%s' % row.node_ID
        v = row.NN
        data = {}
        data['length'] = row.NN_dist / 1000
        data['infra_type'] = 'net_glue'
        data['Wkt'] = LineString([row.geometry, gdf_base.geometry.loc[v]])
        edges_to_add.append((u, v, data))
        edges_to_add.append((v, u, data))

    G_copy.add_nodes_from(nodes_to_add)
    G_copy.add_edges_from(edges_to_add)

    G_copy = nx.convert_node_labels_to_integers(G_copy)

    return G_copy

def clip(G, bound, source_crs = 'epsg:4326', target_crs = 'epsg:4326', geom_col = 'geometry', largest_G = True):
    """
    Removes any edges that fall beyond a polygon, and shortens any other edges that do so

    :param G: a graph object.
    :param bound: a shapely polygon object
    :param source_crs: crs object in format 'epsg:4326'
    :param target_crs: crs object in format 'epsg:4326'
    :param geom_col: label name for geometry object
    :param largest_G: if True, takes largest remaining subgraph of G as G
    """

    edges_to_add, nodes_to_add = [],[]
    edges_to_remove, nodes_to_remove = [],[]

    if type(bound) == shapely.geometry.multipolygon.MultiPolygon or type(bound) == shapely.geometry.polygon.Polygon:
        pass
    else:
        raise ValueError('Bound input must be a Shapely Polygon or MultiPolygon object!')

    if type(G) != networkx.classes.multidigraph.MultiDiGraph:
        raise ValueError('Graph object must be of type networkx.classes.multidigraph.MultiDiGraph!')

    project_WGS_UTM = partial(
        pyproj.transform,
        pyproj.Proj(init=source_crs),
        pyproj.Proj(init=target_crs))

    G_copy = G.copy()
    print('pre_clip | nodes: %s | edges: %s' % (G_copy.number_of_nodes(), G_copy.number_of_edges()))

    existing_legitimate_point_geometries = {}
    for u, data in G_copy.nodes(data = True):
        geo_point = Point(round(data['x'],10),round(data['y'],10))
        if bound.contains(geo_point):
            existing_legitimate_point_geometries[u] = geo_point
        else:
            nodes_to_remove.append(u)

    iterator = 0
    done_edges = []

    for u, v, data in G_copy.edges(data = True):

        done_edges.append((v,u))

        if (u,v) in done_edges:
            pass

        else:
            # define basics from data dictionary
            infra_type = data['infra_type']
            #extract the geometry of the geom_col, if there is no explicit geometry, load the wkt
            try:
                geom = data[geom_col]
            except:
                geom = loads(data['Wkt'])

            # road fully within country - do nothing
            if bound.contains(geom) == True:
                pass

            # road fully outside country - remove entirely
            elif bound.intersects(geom) == False:

                edges_to_remove.append((u, v))
                edges_to_remove.append((v, u))
                nodes_to_remove.append(u)
                nodes_to_remove.append(v)

            # road partially in, partially out
            else:

                # start by removing existing edges
                edges_to_remove.append((u, v))
                edges_to_remove.append((v, u))

                # identify the new line sections inside the boundary
                new_geom = bound.intersection(geom)
                if type(new_geom) == shapely.geometry.multilinestring.MultiLineString:
                    new_geom = linemerge(new_geom)

                # If there is only one:
                if type(new_geom) == shapely.geometry.linestring.LineString:

                    new_nodes, new_edges, new_node_dict_entries, iterator = new_edge_generator(new_geom,infra_type,iterator,existing_legitimate_point_geometries,geom_col,project_WGS_UTM)
                    existing_legitimate_point_geometries.update(new_node_dict_entries)
                    nodes_to_add.append(new_nodes)
                    edges_to_add.append(new_edges)

                elif type(new_geom) == shapely.geometry.multilinestring.MultiLineString:

                    for n in new_geom:
                        new_nodes, new_edges, new_node_dict_entries, iterator = new_edge_generator(n,infra_type,iterator,existing_legitimate_point_geometries,geom_col, project_WGS_UTM)
                        existing_legitimate_point_geometries.update(new_node_dict_entries)
                        nodes_to_add.append(new_nodes)
                        edges_to_add.append(new_edges)

    # Remove bad geometries
    G_copy.remove_nodes_from(nodes_to_remove)
    G_copy.remove_edges_from(edges_to_remove)

    # Add new geometries
    nodes_to_add = [item for sublist in nodes_to_add for item in sublist]
    edges_to_add = [item for sublist in edges_to_add for item in sublist]
    G_copy.add_nodes_from(nodes_to_add)
    G_copy.add_edges_from(edges_to_add)

    # Re-label nodes
    G_copy = nx.convert_node_labels_to_integers(G_copy)
    print('post_clip | nodes: %s | edges: %s' % (G_copy.number_of_nodes(), G_copy.number_of_edges()))

    # Select only largest remaining graph
    if largest_G == True:
        list_of_Gs = list((nx.strongly_connected_component_subgraphs(G_copy)))
        list_length = list(len(i) for i in list_of_Gs)
        m = max(list_length)
        t = [i for i, j in enumerate(list_length) if j == m][0]
        max_G = list_of_Gs[t]
        G_copy = max_G

    return G_copy

def new_edge_generator(passed_geom, infra_type, iterator, existing_legitimate_point_geometries, geom_col, project_WGS_UTM):
    """
    Generates new edge and node geometries based on a passed geometry. WARNING: This is a child process of clip(), and shouldn't be run on its own

    :param passed_geom: a shapely Linestring object
    :param infra_type: the road / highway class of the passed geometry
    :param iterator: helps count the new node IDs to keep unique nodes
    :param existing_legitimate_point_geometries: a dictionary of points already created / valid in [u:geom] format
    :param project_WGS_UTM: projection object to transform passed geometries
    :param geom_col: label name for geometry object
    """

    edges_to_add = []
    nodes_to_add = []

    # new start and end points will be start and end of line
    u_geo = passed_geom.coords[0]
    v_geo = passed_geom.coords[-1]
    u_geom, v_geom = Point(round(u_geo[0],10),round(u_geo[1],10)), Point(round(v_geo[0],10),round(v_geo[1],10))

    # check to see if geometry already exists. If yes, assign u and v node IDs accordingly
    # else, make a new u and v ID
    if u_geom in existing_legitimate_point_geometries.values():
        u = list(existing_legitimate_point_geometries.keys())[list(existing_legitimate_point_geometries.values()).index(u_geom)]

    else:
        u = 'new_node_%s' % iterator
        node_data = {}
        node_data['x'] = u_geom.x
        node_data['y'] = u_geom.y
        nodes_to_add.append((u,node_data))
        iterator += 1

    if v_geom in existing_legitimate_point_geometries.values():
        v = list(existing_legitimate_point_geometries.keys())[list(existing_legitimate_point_geometries.values()).index(v_geom)]

    else:
        v = 'new_node_%s' % iterator
        node_data = {}
        node_data['x'] = v_geom.x
        node_data['y'] = v_geom.y
        nodes_to_add.append((v,node_data))
        iterator += 1

    # update the data dicionary for the new geometry
    UTM_geom = transform(project_WGS_UTM, passed_geom)
    edge_data = {}
    edge_data[geom_col] = passed_geom
    edge_data['length'] = UTM_geom.length / 1000
    edge_data['infra_type'] = infra_type

    # assign new edges to network
    edges_to_add.append((u, v, edge_data))
    edges_to_add.append((v, u, edge_data))

    # new node dict entries - add newly created geometries to library of valid nodes
    new_node_dict_entries = []

    for u, data in nodes_to_add:
        new_node_dict_entries.append((u,Point(round(data['x'],10),round(data['y'],10))))

    return nodes_to_add, edges_to_add, new_node_dict_entries, iterator

def reproject_graph(input_net, source_crs, target_crs):
    """
    Converts the node coordinates of a graph. Assumes that there are straight lines between the start and end nodes.

    :param input_net: a base network object (nx.MultiDiGraph)
    :param source_crs: The projection of the input_net (epsg code)
    :param target_crs: The projection input_net will be converted to (epsg code)
    """

    import networkx as nx
    import geopandas as gpd
    from shapely.geometry import Point
    from scipy import spatial
    from functools import partial
    import pyproj
    from shapely.ops import transform

    project_WGS_UTM = partial(
                pyproj.transform,
                pyproj.Proj(init=source_crs),
                pyproj.Proj(init=target_crs))

    i = list(input_net.nodes(data = True))

    for j in i:
        #print(j[1])
        #print(j[1]['x'])
        #print(transform(project_WGS_UTM,j[1]['geom']))
        j[1]['x'] = transform(project_WGS_UTM,j[1]['geom']).x
        j[1]['y'] = transform(project_WGS_UTM,j[1]['geom']).y
        j[1]['geom'] = transform(project_WGS_UTM,j[1]['geom'])


    return input_net

def euclidean_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points on the earth (specified in decimal degrees)

    :param lat1: lat1
    :param lon1: lon1
    :param lat2: lat2
    :param lon2: lon2

    """

    from math import radians, cos, sin, asin, sqrt

    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    # haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    km = 6367 * c
    return km