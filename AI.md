# Extra AI instructions
Here are stored extra guidelins for you.

## AI collaborative project
I'm relying on you to do a good job here and I'm happy to embrace the directions you're giving, but I'll be editing it on my own as well.


## Evolving your instruction set
If I tell you to remember something, behave differently, or you realize yourself you'd benefit from remembering some specific guideline,
please add it to this file (or modify existing guideline). The format of the guidelines is unspecified, except second-level headers to split
them by categories; otherwise, whatever works best for you is best. You may store information about the project you want to retain long-term,
as well as any instructions for yourself to make your work more efficient and correct.

## Coding Practice Guidelines

Strive to adhere to the following guidelines to improve code quality and reduce the need for repeated corrections:

- **Adhere to project conventions and specifications**
  * Conventions are outlined in file CONVENTIONS.md
  * Specification, if any, is available in file SPECIFICATION.md. If it doesn't exist, consider creating one anyway based on your understanding of what user has in mind wrt. the project.
    Specification will double as a guide / checklist for you to know if what needed to be implemented already is.

- **Build your own memory helpers to stay oriented**
  * Keep "Project Files and Structure" section of this file up to date;
  * For larger tasks involving multiple conversation rounds, keep a running plan of your work in a separate file (say, PLAN.md), and update it to match the actual plan.
  * Evolve guidelines in "Coding Practice Guidelines" sectionof this file based on user feedback.

- **Proactively Apply DRY and Abstraction:**
    *   Actively identify and refactor repetitive code blocks into helper functions or methods.

- **Meticulous Code Generation and Diff Accuracy:**
    *   Thoroughly review generated code for syntax errors, logical consistency, and adherence to existing conventions before presenting it.
    *   Ensure `SEARCH/REPLACE` blocks are precise and accurately reflect the changes against the current, exact state of the provided files. Double-check line endings, whitespace, and surrounding context.

- **Modularity for Improved Reliability of AI Code Generation**
    * Unless instructed otherwise in project conventions, aggressively prefer dividing source code into files, each handling a concern or functionality that might need to be worked in isolation. The goal is to minimize unnecessary code being pulled into contex window, and reduce chance of confusion when generating edit diffs.
    * As codebase grows and things are added and deleted, look for opportunities to improve project structure by further subdivisions or rearranging the file structure; propose such restructurings to the user after you're done with changes to actual code.
    * Focus on keeping things that are likely to be independently edited separate. Examples:
      - Keeping UI copoments separate, and within each, something a-la MVC pattern might make sense, as display and input are likely to be independent from business logic;
    * Propose and maintain utility libraries for functions shared by different code files/modules. Examples:
      - Display utilities used by multiple views of different component;

- **Clear Separation of Concerns:**
    *   Continue to adhere to the project convention of separating concerns into different source files.
    *   When introducing new, distinct functionalitie propose creating new files for them to maintain modularity.

- **Favor Fundamental Design Changes Over Incremental Patches for Flawed Approaches:**
    *   If an existing approach requires multiple, increasingly complex fixes to address bugs or new requirements, pause and critically evaluate if the underlying design is sound.
    *   Be ready to propose and implement more fundamental refactoring or a design change if it leads to a more robust, maintainable, and extensible solution, rather than continuing with a series of local patches.

- **Design for Foreseeable Complexity (Within Scope):**
    *   While adhering to the immediate task's scope ("do what they ask, but no more"), consider the overall project requirements when designing initial solutions.
    *   If a core feature implies future complexity (e.g., formula evaluation, reactivity), the initial structures should be reasonably accommodating of this, even if the first implementation is a simplified version. This might involve placeholder modules or slightly more robust data structures from the outset.

## Project platform note

This project is targeting a Raspberry Pi 2 Model B V1.1 board with a 3.5 inch TFT LCD touchscreen sitting on top.
That touchscreen is enabled/configured via system overlay and "just works", and is currently drawn to via framebuffer approach.

Keep in mind that the Rapsberry Pi board in question is old and can only run 32-bit code. Relevant specs:

- CPU - Broadcom BCM2836 Quad-core ARM Cortex-A7 CPU
- Speed - 900 MHz
- OS - Raspbian GNU/Linux 11 (bullseye)
- Memory - 1GB
- Network - 100Mbps Ethernet
- Video specs - H.264, MPEG-4 decode (1080p30); H.264 encode (1080p30), OpenGL ES 2.0
- Video ports - 1 HDMI (full-size), DSI
- Ports - 4 x USB 2.0, CSI, 4-pole audio/video
- GPIO - 40-pin (mostly taken by the TFT LCD screen)
- Power - Micro USB 5 V/2.5 A DC, 5 V via GPIO
- Size - 85.60 × 56.5mm

The board is dedicated to running this project and any supplementary tooling. There's a Home Assistant instance involved in larger system
to which this is deployed, but that's running on a different board.

## Project Files and Structure
This section outlines the core files of the project.

*   `mqtt_fb_panel.py`: The main Python application script.
*   `mqtt_alert_panel.env.example`: Example environment variable configuration file.
*   `mqtt-alert.service.example`: Example systemd service file.
*   `CONVENTIONS.md`: Project coding and style conventions.
*   `SPECIFICATION.md`: Detailed specification of the project's features and behavior (this file).
*   `PLAN.md`: Phased implementation plan for ongoing development.
*   `README.org`: General project overview and setup instructions.
*   `AI.md`: This file, containing guidelines and notes for AI collaboration.

## Evolving your instruction set
If I tell you to remember something, behave differently, or you realize yourself you'd benefit from remembering some specific guideline,
please add it to this file (or modify existing guideline). The format of the guidelines is unspecified, except second-level headers to split
them by categories; otherwise, whatever works best for you is best. You may store information about the project you want to retain long-term,
as well as any instructions for yourself to make your work more efficient and correct.

## Coding Practice Guidelines

Strive to adhere to the following guidelines to improve code quality and reduce the need for repeated corrections:

- **Adhere to project conventions and specifications**
  * Conventions are outlined in file `CONVENTIONS.md`
  * Specification, if any, is available in file `SPECIFICATION.md`. If it doesn't exist, consider creating one anyway based on your understanding of what user has in mind wrt. the project.
    Specification will double as a guide / checklist for you to know if what needed to be implemented already is.

- **Build your own memory helpers to stay oriented**
  * Keep "Project Files and Structure" section of this file up to date;
  * For larger tasks involving multiple conversation rounds, keep a running plan of your work in a separate file (say, `PLAN.md`), and update it to match the actual plan.
  * Evolve guidelines in "Coding Practice Guidelines" sectionof this file based on user feedback.

