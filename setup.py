from setuptools import setup

setup(
    name="manga-scan-binarize",
    version="0.1.0",
    description="High-quality binarization for scanned manga pages preserving screentones, optimized for vectorization (potrace / Illustrator).",
    author="Yos Awed",
    license="MIT",
    py_modules=["manga_binarize"],
    install_requires=[
        "numpy>=1.24",
        "opencv-python-headless>=4.8",
        "pillow>=10.0",
    ],
    entry_points={
        "console_scripts": [
            "manga-binarize=manga_binarize:main",
        ],
    },
    python_requires=">=3.9",
)
