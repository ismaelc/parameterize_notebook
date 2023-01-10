# parameterize_notebook

This parameterizes your Jupyter notebook by reading each cell and adding string literals as variable-value pairs at the top of the notebook (tagged with 'parameters'). Useful if you're using Papermill.

You can also find the accompanying blog post to this - https://chrispogeek.medium.com/parameterize-your-notebook-jobs-in-amazon-sagemaker-studio-89266fa5d287

### Usage

    from parameterize import parameterize_notebook
    
    parameterize_notebook('input.ipynb', 'output.ipynb')
    

![](https://i.postimg.cc/xCC2mBh8/parameterize-notebook.png)
    
    

