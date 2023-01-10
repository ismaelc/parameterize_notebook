import os
import re
import json
import nbformat


def parameterize_notebook(input_notebook, output_notebook, snippet=''):
    """Modify a Jupyter notebook by replacing literal assignments with parameter assignments, added as global variables tagged with `parameters` at the top of the notebook.

    Args:
        input_notebook (str): The path to the input Jupyter notebook.
        output_notebook (str): The path to the output Jupyter notebook.
        snippet (str, optional): The snippet to add to the output notebook. If 'nbrun', a URI snippet will be added. If any other non-empty string, the provided snippet will be added. If an empty string or not provided, no snippet will be added.

    """
    param_dict = replace_literal_assignments(input_notebook, output_notebook)
    print(json.dumps(param_dict, indent=2))
    if snippet.lower() == 'nbrun':
        add_params_uri_snippet(output_notebook)
    add_papermill_params(output_notebook, param_dict)
    if len(snippet):
        add_snippet(output_notebook, param_dict, snippet=snippet)
    print('Done')


def replace_literal_assignments(ipynb_file, output_ipynb_file):
    """
    Replace literal value assignments in a Jupyter notebook with parameter references.

    Parameters:
        ipynb_file (str): the path to the input Jupyter notebook file
        output_ipynb_file (str): the path to the output Jupyter notebook file

    Returns:
        dict: a dictionary of parameter names and their corresponding values
    """
    # Open the ipynb file and read its contents
    with open(ipynb_file, 'r') as f:
        contents = json.load(f)

    param_list = []
    param_value_dict = {}

    # Compile a regular expression to match lines starting with def, for, while, or import
    control_flow_regex = re.compile(r'^(def|for|while|import|#|from)')

    # Iterate through all cells in the notebook
    for cell in contents['cells']:

        # Check if the cell is a code cell
        if cell['cell_type'] == 'code':

            # Split the cell's source code into lines
            lines = cell['source']

            # Iterate through the lines of code
            for i, line in enumerate(lines):

                # Skip lines starting with def, for, while, or import
                if control_flow_regex.match(line.strip()):
                    continue

                # TODO: Handle this
                if '"""' in line:
                    continue

                new_line = line
                if not len(line.strip()):
                    continue

                # Use the regex pattern to search for variable-value pairs
                # In plain English, this regular expression matches patterns like these:
                #    foo = "bar"
                #    baz: 'qux'
                #    hello = "world"
                matches = re.finditer(
                    r"([^=,]+)\s*(?:=|:)\s*(?:\"([^\"]+)\"|'([^']+)')", line, re.MULTILINE)

                # Iterate through the quoted matches and get the variable and value for each pair
                for matchNum, match in enumerate(matches, start=1):

                    for groupNum in range(0, len(match.groups())):
                        groupNum += 1
                        if groupNum == 1 and match.group(1):
                            variable = match.group(1)
                        elif match.group(groupNum):
                            value = match.group(groupNum)

                    if not variable or not value:
                        continue
                    if not len(value.strip()):
                        continue

                    param_name, param_list, param_value_dict = process_parameter_dict(
                        value, variable, param_list, param_value_dict)
                    new_line = update_new_line(new_line, value, param_name)

                # Iterate through notebook environment variables
                line = new_line
                while True:
                    if '%env' not in line:
                        break

                    variable, value = extract_env_key_value(new_line)

                    if not variable or not value:
                        # Break here limits us to single env variable per line
                        break

                    param_name, param_list, param_value_dict = process_parameter_dict(
                        value, variable, param_list, param_value_dict)
                    new_line = update_new_line(
                        new_line, value, f'${param_name}')
                    line = new_line.replace('%env', '')

                # Match files if missed above
                files = get_file_references(new_line)
                for file in files:
                    filename = file[1]
                    extension = file[2]
                    variable = extension.upper() if len(
                        extension) else filename[:2].upper()
                    #param_name, param_list = add_to_param_dict(variable, param_list)
                    #param_value_dict[param_name] = f'{filename}.{extension}'
                    value = f'{filename}.{extension}'
                    param_name, param_list, param_value_dict = process_parameter_dict(
                        value, variable, param_list, param_value_dict)
                    #new_line = update_new_line(new_line, f'{filename}.{extension}', param_name)
                    new_line = update_new_line(new_line, value, param_name)

                # Match s3_uri from a bash command
                if new_line.startswith('!'):
                    extracted_s3_uri = extract_s3_uri(new_line)
                    if len(extracted_s3_uri):
                        variable = 'S3_URI'
                        value = extracted_s3_uri
                        param_name, param_list, param_value_dict = process_parameter_dict(
                            value, variable, param_list, param_value_dict)
                        new_line = update_new_line(
                            new_line, value, "{" + param_name + "}")

                lines[i] = new_line

    # Run another pass to replace quoted parameters with those already captured in param_value_dict
    for cell in contents['cells']:
        if cell['cell_type'] == 'code':
            cell['source'] = update_quoted_parameters(
                cell['source'], param_value_dict)

    # Write the modified contents back to the ipynb file
    with open(output_ipynb_file, 'w') as f:
        json.dump(contents, f)

    return param_value_dict


def process_parameter_dict(value: str, variable: str, param_list: list, param_value_dict: dict) -> tuple:
    """
    Process a parameter value and add it to a dictionary of parameters.

    Parameters:
    - value (str): The value of the parameter to be processed.
    - variable (str): The name of the variable associated with the parameter.
    - param_list (list): A list of parameter names.
    - param_value_dict (dict): A dictionary mapping parameter names to their values.

    Returns:
    - tuple: A tuple containing the parameter name, the updated list of parameter names, and the updated dictionary of parameter values.
    """
    temp_key = get_key(param_value_dict, value)
    if temp_key is not None:
        # Value already exists in dictionary. Return the existing param (temp_key) instead of updating the dict
        param_name = temp_key
    else:
        param_name, param_list = add_to_param_dict(
            get_alphanumeric(variable), param_list)
        param_value_dict[param_name] = value.strip('"').strip("'")
    return param_name, param_list, param_value_dict


def update_new_line(orig_line: str, orig_text: str, new_text: str) -> str:
    """
    Replace a string in a line of text and remove quotes around the new string.

    Parameters:
    - orig_line (str): The original line of text.
    - orig_text (str): The string to be replaced.
    - new_text (str): The replacement string.

    Returns:
    - str: The modified line of text.
    """
    #new_line = orig_line.replace(orig_text, new_text, 1)
    #new_line = remove_quotes_around_string(new_line, new_text)
    new_line = orig_line.replace(f'"{orig_text}"', new_text, 1) if f'"{orig_text}"' in orig_line else orig_line.replace(
        f"'{orig_text}'", new_text, 1).replace(orig_text, new_text, 1)
    return new_line


def update_quoted_parameters(nb_source_lines: list, param_value_dict: dict) -> None:
    """
    Update the quoted parameters in a list of lines of code with corresponding values from a dictionary.

    Parameters:
    - nb_source_lines (list): A list of lines of code to be modified.
    - param_value_dict (dict): A dictionary mapping parameter names to their values.

    Returns:
    - list: A list of modified lines of code.
    """
    return [replace_quoted_string_with_dict_key(line, param_value_dict) for line in nb_source_lines]


def replace_quoted_string_with_dict_key(line: str, value_dict: dict) -> None:
    """
    Replace a string in a line of text with the key from a dictionary matching its value.

    Parameters:
    - line (str): The line of text to be modified.
    - value_dict (Dict[str, str]): A dictionary mapping keys to values.

    Returns:
    - str: The modified line of text.
    """
    # Iterate over the items in the dictionary
    for key, value in value_dict.items():
        # Check if the value matches the string in the line
        if value not in line:
            continue

        while True:
            quoted_text = get_quoted_text(line)
            if quoted_text is None:
                break
            line_temp = line
            #print(quoted_text.strip('"').strip("'"), value)
            if quoted_text.strip('"').strip("'") == value:
                line = line.replace(quoted_text, key)
            if line == line_temp:
                break
    return line


def extract_env_key_value(line):
    """Extracts the key and value from a line beginning with %env and separating the key and value with an = character.

    Args:
        line (str): The line to extract the key and value from.

    Returns:
        tuple: A tuple containing the key and value.
    """
    match = re.search(
        r"%env\s+([^=,]+)\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s,]+))", line)
    if match:
        key = match.group(1)
        value = match.group(2) or match.group(3) or match.group(4)
        return key, value
    return None, None


def extract_s3_uri(line: str) -> str:
    """
    Extract an S3 URI from a line in a Jupyter notebook.

    Parameters:
    - line (str): The line to extract the S3 URI from.

    Returns:
    - str: The extracted S3 URI.
    """
    # Compile a regular expression to match an S3 URI
    s3_uri_regex = re.compile(r'(s3://[^\s]+)')

    # Match the S3 URI in the line
    match = s3_uri_regex.search(line)
    if match:
        # Return the matched S3 URI
        return match.group(1)
    else:
        # Return an empty string if no S3 URI was found
        return ''


def get_key(dictionary: dict, value: any) -> any:
    """
    Get the key of a value in a dictionary.

    Parameters:
    - dictionary (dict): The dictionary to search.
    - value (any): The value to search for.

    Returns:
    - any: The key of the value, or None if the value is not found in the dictionary.
    """
    for key, val in dictionary.items():
        if val.strip().strip('\n') == value.strip().strip('\n'):
            return key
    return None


def add_to_param_dict(variable: str, param_list: list) -> tuple:
    """
    Add a parameter to a list of parameters, with a unique name.

    Parameters:
    - variable (str): The name of the variable associated with the parameter.
    - param_list (list): A list of parameter names.

    Returns:
    - tuple: A tuple containing the generated parameter name and the updated list of parameter names.
    """
    param_name = f'PARAM_{variable}'
    if param_name not in param_list:
        param_list.append(param_name)
    else:
        param_name, param_list = increment_param_name(variable, param_list)

    return param_name, param_list


def increment_param_name(variable, param_list=[]):
    """
    Generate a unique parameter name based on a variable name.

    Parameters:
    - variable (str): The name of the variable associated with the parameter.
    - param_list (list): A list of parameter names (optional).

    Returns:
    - tuple: A tuple containing the generated parameter name and the updated list of parameter names.
    """
    ctr = 2
    while True:
        param_name = f'PARAM_{variable}_{ctr}'
        if param_name not in param_list:
            param_list.append(param_name)
            break
        ctr += 1
    return param_name, param_list


def get_alphanumeric(variable: str) -> str:
    """Extracts an alphanumeric variable from a string and returns it in uppercase.

    Args:
        variable (str): The string to extract the alphanumeric variable from.

    Returns:
        str: The extracted alphanumeric variable in uppercase.
    """
    variable = variable.strip().strip('"').strip("'").upper()

    match_alphanumeric = re.findall(r'\b[a-zA-Z0-9]+\b', variable)
    if len(match_alphanumeric):
        variable = match_alphanumeric.pop().strip()
    return variable


def remove_quotes_around_string(line, string):
    """Remove quotes from around a given string within a line of text.

    Args:
        line (str): The line of text to search.
        string (str): The string to remove quotes from.

    Returns:
        str: The modified line of text with quotes removed from around the given string.

    Example:
        line = "The string 'hello' will be unquoted."
        string = "hello"
        remove_quotes_around_string(line, string)
        >> "The string hello will be unquoted."
    """
    new_line = line
    matches = re.finditer(
        r'(?P<quote>["\'])(?P<string>.*?)(?P=quote)', line, re.MULTILINE)

    for matchNum, match in enumerate(matches, start=1):
        for groupNum in range(0, len(match.groups())):
            groupNum += 1
            if match.group('string') == string:

                # Extract the quote type and the string
                quote = match.group('quote')
                matched_string = match.group('string')

                # Replace the quoted string with the unquoted string
                new_line = re.sub(
                    f"{quote}{matched_string}{quote}", matched_string, line)

    return new_line


def get_file_references(line):
    """
    Extract file references from a given string.

    Parameters:
    - line (str): The input string to extract file references from.

    Returns:
    - List[Tuple[str, str, str]]: A list of tuples containing file references. Each tuple consists of
      a quote character (either single or double quotes), the file name, and the file extension.

    Example:
    - get_file_references('This is a file "xxx.csv" and another one 'hey.pkl'')
      returns [('"', 'xxx', 'csv'), ("'", 'hey', 'pkl')]

    """

    extensions = ['pkl', 'pk', 'csv', 'joblib', 'onnx', 'ipynb']
    pattern = get_pattern(extensions)
    #pattern = r'(["\'])([^"\']+\.pkl|[^"\']+\.csv|[^"\']+\.joblib|[^"\']+\.onnx|[^"\']+\.ipynb|s3://[^"\']+)\1'
    matches = re.findall(pattern, line)

    updated_matches = []
    for match in matches:
        quote, filepath = match
        filename, extension = os.path.splitext(filepath)
        updated_matches.append((quote, filename, extension[1:]))

    return updated_matches


def get_pattern(extensions):
    extensions_pattern = '|'.join([f'[^"\']+\.{ext}' for ext in extensions])
    return r'(["\'])({extensions_pattern}|s3://[^"\']+)\1'.format(extensions_pattern=extensions_pattern).replace("[^\"']", '[^"\\\''']')


def get_quoted_text(text: str):
    """
    Extract the text between quotes (either single or double quotes) from the given string.

    Args:
        text (str): The input string to search for quoted text.

    Returns:
        Union[str, None]: The quoted text, including the quotes, if a match is found. Otherwise, returns None.
    """
    # Use a regular expression to extract the text between quotes
    #match = re.search(r'[\'"](.*?)[\'"]', text)
    match = re.search(r'"(.*?)"|\'(.*?)\'', text)
    if match:
        # Return the quoted text, including the quotes
        return match.group(0)
    else:
        # If no match is found, return None
        return None


def inject_code_at_top(nb, code, tag=None):
    """
    Insert a new code cell at the top of a Jupyter notebook.

    Parameters:
        nb (dict): a Jupyter notebook object
        code (str): a string containing the code to be added to the new cell
        tag (str): a string representing a tag to be associated with the new cell
    """
    # Create a new code cell at the top of the notebook
    new_cell = nbformat.v4.new_code_cell(source=code)

    # Add the tag to the cell
    new_cell.metadata['tags'] = [tag]

    # Insert the new cell at the top of the notebook
    nb['cells'].insert(0, new_cell)


def add_papermill_params(notebook_file, params_dict):
    """
    Add parameter definitions to a Jupyter notebook to be used with Papermill.

    Parameters:
        notebook_file (str): the path to the Jupyter notebook file
        params_dict (dict): a dictionary of parameter names and values to be added to the notebook
    """
    # Read the notebook from a file
    with open(notebook_file, 'r') as f:
        nb = nbformat.read(f, as_version=4)

    # print(params_dict)
    code = ''
    for key, value in params_dict.items():
        if '"' in value:
            code += f"{key} = '{value}'\n"
        else:
            code += f'{key} = "{value}"\n'

    # Specific to NBRun, harmless to Papermill
    code += 'params_uri = ""'

    # Inject the code at the top of the notebook
    inject_code_at_top(nb, code, 'parameters')

    # Write the modified notebook to a file
    with open(notebook_file, 'w') as f:
        nbformat.write(nb, f)


def add_snippet(output_notebook, param_dict, snippet=""):

    with open(output_notebook, 'r') as f:
        nb = nbformat.read(f, as_version=4)

    if snippet.lower() == 'papermill':
        inject_code_at_top(nb, papermill_snippet(output_notebook, param_dict))
    elif snippet.lower() == 'nbrun':
        inject_code_at_top(nb, nbrun_snippet(output_notebook, param_dict))

    with open(output_notebook, 'w') as f:
        nbformat.write(nb, f)


def add_params_uri_snippet(output_notebook):
    """Add a snippet to the top of a Jupyter notebook.

    Args:
        output_notebook (str): The path to the output Jupyter notebook.
        param_dict (dict): A dictionary of parameter values.
        snippet (str, optional): The type of snippet to add. If 'papermill', a papermill snippet will be added. If 'nbrun', an nbrun snippet will be added. If not provided or an empty string, no snippet will be added.
    """
    with open(output_notebook, 'r') as f:
        nb = nbformat.read(f, as_version=4)

    inject_code_at_top(nb, params_uri_snippet())

    with open(output_notebook, 'w') as f:
        nbformat.write(nb, f)


def papermill_snippet(notebook_file, param_dict):

    param_dict = json.dumps(param_dict, indent=8)

    text = f"""# PAPERMILL SNIPPET
\"\"\"
!pip install papermill --quiet
!mkdir notebook_output
import papermill as pm

p = pm.execute_notebook(
    "{notebook_file}",
    "notebook_output/o-{notebook_file}",
    parameters={param_dict},
    kernel_name="python3",
)
\"\"\"
"""
    return text


def nbrun_snippet(notebook_file, param_dict):

    param_dict['params_uri'] = ''
    param_dict = json.dumps(param_dict, indent=8)

    text = f"""# NBRUN SNIPPET
\"\"\"
!rm -rf NBRun.py && aws s3 cp s3://dsml-us-ml-dev-data-scripts/team/concur-ml/concurml/jupyter/NBRunTest.py NBRun.py --quiet
!mkdir notebook_output
from NBRun import NBRun
import papermill as pm

n = NBRun(
    instance_type="ml.p3.8xlarge",
    image="notebook-runner-tf",
    nb_uri="{notebook_file}",
    params={param_dict},
    params_to_s3=True,
)
print(n.job_name)
n.status()
n.wait()
n.download_notebook(folder='notebook_output')
\"\"\"
"""
    return text


def params_uri_snippet():
    return """import json

if params_uri != '':
    !aws s3 cp s3://dsml-us-ml-dev-data-scripts/team/concur-ml/concurml/jupyter/utils.py . --quiet
    from utils import get_params_from_s3
    params = get_params_from_s3(params_uri)
    for key in params:
        print(key, params[key])
        globals()[key] = params[key]"""
