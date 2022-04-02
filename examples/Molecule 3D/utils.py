import os
from textwrap import dedent
from fast_dash.Components import dcc

import dash_bio
from dash_bio.utils import pdb_parser as parser, mol3dviewer_styles_creator as sparser


DATAPATH = 'data'

data_info = {
    'Measles Nucleocapsid': {
        'name': 'Measles Nucleocapsid',
        'path': os.path.join(DATAPATH, '4uft.pdb'),
        'description': dedent(r'''
        The measles nucleoprotein forms a large helical complex with
        RNA... It is thought to chaperone the process of replication and
        transcription by providing a site ready for binding of the
        polymerase/phosphoprotein complex while a new RNA chain is being
        built.
        The structure includes the stable core domain of the
        nucleoprotein and a strand of RNA, but the flexible tail of
        nucleoprotein was removed in this study.
        '''),
        'link': 'http://pdb101.rcsb.org/motm/231'
    },

    'a-cobratoxin-AChBP complex': {
        'name': 'a-cobratoxin-AChBP complex',
        'path': os.path.join(DATAPATH, '1yi5.pdb'),
        'description': dedent(r'''
        The crystal structure of the snake long alpha-neurotoxin,
        alpha-cobratoxin, bound to the pentameric
        acetylcholine-binding protein (AChBP) from Lymnaea
        stagnalis...
        The structure unambiguously reveals the positions and
        orientations of all five three-fingered toxin molecules
        inserted at the AChBP subunit interfaces and the
        conformational changes associated with toxin binding.
        '''),
        'link': 'https://www.rcsb.org/structure/1yi5'
    },

    'Calcium ATPase': {
        'name': 'Calcium ATPase',
        'path': os.path.join(DATAPATH, '1su4.pdb'),
        'description': dedent(r'''
        The calcium pump allows muscles to relax after... \[muscle\]
        contraction. The pump is found in the membrane of the
        sarcoplasmic reticulum. In some cases, it is so plentiful that
        it may make up 90% of the protein there. Powered by ATP, it
        pumps calcium ions back into the sarcoplasmic reticulum,
        reducing the calcium level around the actin and myosin
        filaments and allowing the muscle to relax.
        \[The structure\] has a big domain poking out on the outside
        of the sarcoplasmic reticulum, and a region that is embedded
        in the membrane, forming a tunnel to the other side.
        '''),
        'link': 'http://pdb101.rcsb.org/motm/51'
    },

    'DNA': {
        'name': 'DNA',
        'path': os.path.join(DATAPATH, '1bna.pdb'),
        'description': dedent(r'''
        DNA is read-only memory, archived safely inside cells. Genetic
        information is stored in an orderly manner in strands of
        DNA. DNA is composed of a long linear strand of millions of
        nucleotides, and is most often found paired with a partner
        strand. These strands wrap around each other in the familiar
        double helix...
        '''),
        'link': 'http://pdb101.rcsb.org/motm/23'
    },

    'T7 RNA Polymerase': {
        'name': 'T7 RNA Polymerase',
        'path': os.path.join(DATAPATH, '1msw.pdb'),
        'description': dedent(r'''
        RNA polymerase is a huge factory with many moving parts. \[The
        constituent proteins\] form a machine that surrounds DNA
        strands, unwinds them, and builds an RNA strand based on the
        information held inside the DNA. Once the enzyme gets started,
        RNA polymerase marches confidently along the DNA copying RNA
        strands thousands of nucleotides long.
        ...
        This structure includes a very small RNA polymerase that is
        made by the bacteriophage T7... \[a\] small transcription
        bubble, composed of two DNA strands and an RNA strand, is
        bound in the active site.
        '''),
        'link': 'http://pdb101.rcsb.org/motm/40'}
}



def render_molecule(molecule):

    data_path = data_info[molecule]['path']

    mol_style = 'cartoon'
    color_style = 'residue'
    # Create the model data from the decoded contents
    pdb = parser.PdbParser(data_path)
    mdata = pdb.mol3d_data()

    # Create the cartoon style from the decoded contents
    data_style = sparser.create_mol3d_style(
        mdata.get("atoms"),
        mol_style,
        color_style
    )

    return [dash_bio.Molecule3dViewer(
            id='mol-3d',
            selectionType='atom',
            modelData=mdata,
            styles=data_style,
            selectedAtomIds=[],
            backgroundOpacity='0',
            atomLabelsShown=False,
        ), dcc.Markdown(data_info[molecule]['description'])]
