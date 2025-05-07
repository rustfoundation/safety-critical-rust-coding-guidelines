# Safety-Critical Rust Coding Guidelines

Coding Guidelines for Safety Critical Rust developed by the [Safety Critical Rust Consortium][safety-critical-rust-consortium].

[View the latest rendered guidelines online](https://rustfoundation.github.io/safety-critical-rust-coding-guidelines/)

_Note_: Early, subject to changes.

## Building the coding guidelines

The Safety-Critical Rust Coding Guidelines use `Sphinx` and `Sphinx-Needs` to build a rendered version of the coding guidelines, and `uv` to install and manage Python dependencies (including Sphinx itself). To simplify building the rendered version, we created a script called `make.py` that takes care of invoking Sphinx with the right flags.

You can build the rendered version by running:

On Linux-like systems:

```shell
   ./make.py
```

On Windows systems:

```shell
   uv run make.py
``` 

By default, Sphinx uses incremental rebuilds to generate the content that
changed since the last invocation. If you notice a problem with incremental
rebuilds, you can pass the `-c` flag to clear the existing artifacts before
building:

```shell
   ./make.py -c
```

The rendered version will be available in `build/html/`.

A machine-parseable artifact will be available at `build/html/needs.json`. (ToDo: Pete LeVasseur) The `needs.json` file could use some cleaning up and some description here of the contents.

A record with checksums of the contents is available at `build/html/guidelines-ids.json`. Users of the coding guidelines can reference this file to determine if there have been changes to coding guidelines contents they should be aware of.


## Running builds offline

If you're working without internet access or want to avoid reaching out to remote resources, you can pass the `--offline` flag:

```shell
   ./make.py --offline
```

This prevents the build system from attempting to fetch remote resources, such as updates to the specification. Use this flag when you need reproducible or air-gapped builds.

It is recommended to use `--offline` if you are running `make.py` frequently during development. The builder fetches data from [the Ferrocene Language Specification website](https://spec.ferrocene.dev/paragraph-ids.json), which may rate-limit repeated requests—leading to delays or failed builds. Using `--offline` can significantly improve build speed and avoid unnecessary network issues during iterative work.


## Build breaking due to out-dated spec lock file

It's a fairly common occurrence for the build to break due to an out of date spec lock file, located at:

```
src/spec.lock
```

The `spec.lock` is checked against the current live version of the specification, which means that your local development may go out of date while you are developing a feature.

### Continuing work while on a feature branch

If you run into this while developing a feature, you may ignore this error by running the build with:

```shell
   ./make.py --ignore-spec-lock-diff
```

### If you need to audit the difference

When the build breaks due to the difference a file is created here:

```
/tmp/fls_diff_<random>.txt
```

which can be used to aid in auditing the differences.

Follow the below steps to ensure that the guidelines remain a representation of the FLS:

1. Check if there are any guidelines currently affected, if no, go to 6.
2. For each affected guideline, audit the previous text and current text of the appropriate paragraph-id in the FLS
3. If the prior and new text of that paragraph in the FLS does not effect the guideline, proceed back to 2. to the next affected guideline
4. If the prior and new text of that paragraph do differ in the FLS, then a rationalization step is required
   1. In the rationalization step, either yourself or another coding guidelines member must modify the guideline to comply with the new text
5. If you any affected coding guidelines remain proceed back to 2. to the next affected guideline
6. You are done

Once you have completed the above steps, you will now update the local copy of the `spec.lock` file with the live version:

```shell
   ./make.py --update-spec-lock-file
```

Open a new PR with only the changes necessary to rationalize the guidelines with the new FLS text.

## Contributing to the coding guidelines

See [CONTRIBUTING.md](CONTRIBUTING.md).

### Chapter layout mirrors Ferrocene Language Specification

We have the same chapter layout as the [Ferrocene Language Specification](https://spec.ferrocene.dev/) (FLS). If you would like to contribute you may find a section from the FLS of interest and then write a guideline in the corresponding chapter of these coding guidelines.

### Guideline template

We have a script `./generate-guideline-templates.py` which which assumes you're using `uv` that can be run to generate the template for a guideline with properly randomized IDs.

You can the copy and paste this guideline from the command line into the correct chapter.

### Filling out the guideline

Reference `src/conf.py` to see valid selections for unfilled options in the guideline template.

Note that the `:fls:` option should be filled according to the FLS paragraph ID for which the guideline is covering. One way to go about finding this is to inspect the page using your web browser. You'll be looking for something like:

```html
<p><span class="spec-paragraph-id" id="fls_4rhjpdu4zfqj">4.1:1</span>
```

You would then pull `fls_4rhjpdu4zfqj` to place in the `:fls:` option.

Existing guidelines can also serve as examples on how guidelines are filled.


## [Code of Conduct][code-of-conduct]

The [Rust Foundation][rust-foundation] has adopted a Code of Conduct that we
expect project participants to adhere to. Please read [the full
text][code-of-conduct] so that you can understand what actions will and will not
be tolerated.

## Licenses

Rust is primarily distributed under the terms of both the MIT license and the
Apache License (Version 2.0), with documentation portions covered by the
Creative Commons Attribution 4.0 International license..

See [LICENSE-APACHE](LICENSE-APACHE), [LICENSE-MIT](LICENSE-MIT), 
[LICENSE-documentation](LICENSE-documentation), and 
[COPYRIGHT](COPYRIGHT) for details.

You can also read more under the Foundation's [intellectual property
policy][ip-policy].

## Other Policies

You can read about other Rust Foundation policies in the footer of the Foundation
[website][foundation-website].

[code-of-conduct]: https://foundation.rust-lang.org/policies/code-of-conduct/
[foundation-website]: https://foundation.rust-lang.org
[ip-policy]: https://foundation.rust-lang.org/policies/intellectual-property-policy/
[media-guide and trademark]: https://foundation.rust-lang.org/policies/logo-policy-and-media-guide/
[rust-foundation]: https://foundation.rust-lang.org/
[safety-critical-rust-consortium]: https://github.com/rustfoundation/safety-critical-rust-consortium
