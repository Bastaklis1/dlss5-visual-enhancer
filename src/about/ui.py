import gradio as gr

from ..core.version import APP_VERSION


def build_about_tab():
    return gr.HTML(
        f"""
        <section class="about-details" aria-labelledby="about-name">
            <h2 id="about-name">DLSS 5 Visual Enhancer</h2>
            <p class="about-version">Version {APP_VERSION}</p>
            <div class="about-links">
                <p>
                    <a href="https://github.com/Merserk/dlss5-visual-enhancer"
                       target="_blank" rel="noopener noreferrer">GitHub</a>
                    <span class="about-description">Source code, updates, and issue reporting.</span>
                </p>
                <p>
                    <a href="https://www.patreon.com/MM744"
                       target="_blank" rel="noopener noreferrer">Support on Patreon</a>
                </p>
            </div>
            <p class="about-copyright">&copy; Merserk</p>
        </section>
        """,
        elem_id="about-content",
        padding=False,
    )
