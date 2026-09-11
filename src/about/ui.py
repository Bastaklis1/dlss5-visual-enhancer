import gradio as gr


def build_about_tab():
    return gr.HTML(
        """
        <section class="about-details" aria-labelledby="about-name">
            <h2 id="about-name">DLSS 5 Visual Enhancer</h2>
            <p class="about-version">Version v8.0</p>
            <div class="about-links">
                <p>
                    <a href="https://github.com/Merserk/dlss5-visual-enhancer"
                       target="_blank" rel="noopener noreferrer">GitHub</a>
                    <span class="about-description">Source code, updates, and issue reporting.</span>
                </p>
                <p>
                    <a href="https://www.patreon.com/Merserk"
                       target="_blank" rel="noopener noreferrer">Patreon</a>
                    <span class="about-description">Support the creator and future development.</span>
                </p>
            </div>
            <p class="about-copyright">&copy; Merserk</p>
        </section>
        """,
        elem_id="about-content",
        padding=False,
    )
