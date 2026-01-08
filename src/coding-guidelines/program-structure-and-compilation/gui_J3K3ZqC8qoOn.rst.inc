.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. guideline:: Prevent OS Command Injection
    :id: gui_J3K3ZqC8qoOn
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
        :id: rat_aOGrRsi4ASsV
        :status: draft

        When preparing a command to be executed by the operating system, untrusted input should be sanitized to make sure it does not alter the syntax of the command to be executed. The easiest way to do this is to avoid string concatenation or formatting (a la ``format!()``), and provide the untrusted data as a lone argument.

    .. non_compliant_example::
        :id: non_compl_ex_p7ZC43gDSy0u
        :status: draft

        The following code lists the contents the directory provided in the ``dir`` variable.. However, since this variable is untrusted, a ``dir`` such as ``dummy && echo BOO`` will cause the command to be executed. Thus, the program prints “BOO”.

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
                let _ = files("dummy & echo BOO");  // Program prints "BOO"
            }


    .. compliant_example::
        :id: compl_ex_pzNJ0Uc5pTtX
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
                let _ = files("dummy & echo BOO");  // Command is invalid, but does not print BOO
            }


    .. compliant_example::
        :id: compl_ex_Eb86EFTC52lj
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
                let _ = files("dummy & echo BOO");  // Command is invalid, but does not print BOO
            }


    .. bibliography::
        :id: bib_sGT6VkRzri7W
        :status: draft

        .. list-table::
           :header-rows: 0
           :widths: auto
           :class: bibliography-table

          * - :bibentry:`gui_J3K3ZqC8qoOn:CERT-J-IDS07`
            - SEI CERT Java. "IDS07-J. Sanitize untrusted data passed to the Runtime.exec() method." https://wiki.sei.cmu.edu/confluence/x/xTdGBQ
