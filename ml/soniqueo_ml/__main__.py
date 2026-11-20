from soniqueo_ml.cli import main

# Guarded: worker processes spawned on Windows import this module and must not re-run the CLI.
if __name__ == "__main__":
    main()
