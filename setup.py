from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="quickinsights",
    version="0.0.1",
    description="QuickInsights AI for Frappe",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Aswin",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=[],
)
