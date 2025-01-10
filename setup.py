from setuptools import setup, find_packages

def read_requirements(filename):
    """Read requirements from file."""
    with open(filename) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="localflow",
    version="0.1.0",
    description="A local workflow execution engine",
    author="Araray Velho",
    author_email="araray@gmail.com",
    packages=find_packages(),
    install_requires=read_requirements('requirements.txt'),
    entry_points={
        'console_scripts': [
            'localflow=localflow.cli.main:cli',
        ],
    },
    python_requires='>=3.8',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)