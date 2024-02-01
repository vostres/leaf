from setuptools import setup, find_packages

setup(
    name='leafxai',
    version='0.1.1',
    description='A Python framework for the quantitative evaluation of eXplainable AI methods.',
    author='@amparore',
    packages=find_packages(),
    install_requires=[
        'numpy>=1.0',
        'pandas>=1.0',
        'lime>=0.2.0',
        'shap>=0.39.0',
        'imbalanced-learn>=0.8.0',
        'tabulate>=0.8.9',
    ],
)