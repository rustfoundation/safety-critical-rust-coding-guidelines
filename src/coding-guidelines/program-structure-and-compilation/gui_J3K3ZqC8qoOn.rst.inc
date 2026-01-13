.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. guideline:: Prevent OS Command Injection
    :id: gui_wecXqgaj3xgj
    :category: mandatory
    :status: draft
    :release: 1.0.0-latest
    :fls: fls_hdwwrsyunir
    :decidability: undecidable
    :scope: module
    :tags: injection,sanitization

    Commands that are passed to an external OS command interpreter, like ``std::process::Command``, should not allow untrusted input to be parsed as part of the command syntax.

    Instead, an untrusted input should be passed as a single argument.

    .. rationale::
        :id: rat_pfOjnJc5Don3
        :status: draft

        When preparing a command to be executed by the operating system, untrusted input should be sanitized to make sure it does not alter the syntax of the command to be executed. For commands that do not tokenize their arguments, such as ``sh``, the easiest way to do this is to avoid mixing untrusted data with trusted data via concatenation or formatting (a la ``format!()``). Instead provide the untrusted data as a lone argument. The ``Command::new()`` constructor makes this easy by accepting the pre-tokenized arguments as a list of strings.

        Traditionally untrusted data should be one argument (aka command-line token). OS command injection occurs when a malicious data fools the command tokenizer into interpreting it as multiple arguments, or even multiple commands. Complexity in the command tokenizer can exacerbate this problem, leading to vulnerabilities such as :cite:`gui_wecXqgaj3xgj:CVE-2024-24576`. See :cite:`gui_wecXqgaj3xgj:RUST-WIN-ARG-SPLIT` and :cite:`gui_wecXqgaj3xgj:SEI-BATBADBUT` for more information.

    .. non_compliant_example::
        :id: non_compl_ex_EDPSvnIyDgMO
        :status: draft

        The following code lists the contents the directory provided in the ``dir`` variable. However, since this variable is untrusted, a ``dir`` such as ``dummy | echo BOO`` will cause the command to be executed. Thus, the program prints “BOO”.

        .. rust-example::

            use std::process::{Command, Output};
            use std::io;

            fn files(dir: &str) -> io::Result<Output> {
                return Command::new("sh")
                    .arg("-c")
                    .arg(format!("ls {dir}"))
                    .output();
            }

            fn main() {
                if cfg!(unix) {
                    let _ = files("dummy | echo BOO");  // Program prints "BOO"
                }
            }


    .. compliant_example::
        :id: compl_ex_Gi1zmSEMepG2
        :status: draft

        An untrusted input should be passed as a single argument. This prevents any spaces or other shell punctuation in the input from being misinterpreted by the OS command interpreter.

        .. rust-example::

            use std::process::{Command, Output};
            use std::io;

            fn files(dir: &str) -> io::Result<Output> {
                return Command::new("ls")
                    .arg(dir)
                    .output();
            }

            fn main() {
                if cfg!(unix) {
                    let _ = files("dummy | echo BOO");  // Command is invalid, but does not print BOO
                }
            }


    .. compliant_example::
        :id: compl_ex_oIfhLciG9rsK
        :status: draft

        A better approach is to avoid OS commands and use a specific API (in this case ``fs::read_dir()``) to achieve the desired result.

        .. rust-example::

            use std::fs;
            use std::io;

            fn files(dir: &str) -> io::Result<Vec<std::ffi::OsString>> {
                return fs::read_dir(dir)?
                    .map(|res| res.map(|e| e.file_name()))
                    .collect();
            }

            fn main() {
                if cfg!(unix) {
                    let _ = files("dummy | echo BOO");  // Command is invalid, but does not print BOO
                }
            }


    .. bibliography::
        :id: bib_G7HkGiWvGowP
        :status: draft

        .. list-table::
           :header-rows: 0
           :widths: auto
           :class: bibliography-table

          * - :bibentry:`gui_wecXqgaj3xgj:CERT-J-IDS07`
            - SEI CERT Java. "IDS07-J. Sanitize untrusted data passed to the Runtime.exec() method." https://wiki.sei.cmu.edu/confluence/x/xTdGBQ
          * - :bibentry:`gui_wecXqgaj3xgj:RUST-WIN-ARG-SPLIT`
            - Module process. "Windows Argument Splitting." https://doc.rust-lang.org/std/process/index.html#windows-argument-splitting
          * - :bibentry:`gui_wecXqgaj3xgj:SEI-BATBADBUT`
            - SEI Blog. "What Recent Vulnerabilities Mean to Rust | “BatBadBut” Command Injection with Windows’ cmd.exe (CVE-2024-24576)." https://www.sei.cmu.edu/blog/what-recent-vulnerabilities-mean-to-rust/
          * - :bibentry:`gui_wecXqgaj3xgj:CVE-2024-24576`
            - MITRE. "CVE-2024-24576." https://nvd.nist.gov/vuln/detail/CVE-2024-24576
