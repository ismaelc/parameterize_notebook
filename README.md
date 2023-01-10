# parameterize_notebook

This parameterizes your Jupyter notebook by reading each cell and adding string literals as variable-value pairs at the top of the notebook (tagged with 'parameters'). Useful if you're using Papermill

### Usage

    from parameterize import parameterize_notebook
    
    parameterize_notebook('input.ipynb', 'output.ipynb')
    
    
You can also find the accompanying blog post to this - 
