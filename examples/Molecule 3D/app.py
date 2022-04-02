from fast_dash import FastDash, Fastify
from fast_dash.Components import Text, dcc, html
from utils import render_molecule, data_info

mol_dropdown = Fastify(dcc.Dropdown(options=[{'label':k, 'value':k} for k in data_info]), 'value')
output_div = Fastify(html.Div(), 'children')

app = FastDash(callback_fn=render_molecule, 
                inputs=mol_dropdown, 
                outputs=output_div, 
                title='Molecule 3D Viewer',
                subheader="Molecule3D is a visualizer that allows you to view biomolecules in multiple representations: sticks, spheres, and cartoons.",
                title_image_path="https://raw.githubusercontent.com/dkedar7/fast_dash/examples/examples/Molecule%203D/assets/molecule.png",
                theme="Pulse")

if __name__ == '__main__':
    app.run()