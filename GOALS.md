# Goals

## Elevator pitch

We will make Rust coding guidelines available within this repository. The coding guidelines will additionally be deployed to an accessible location on the internet. These coding guideliens will comply with relevant standards for various safety-critical industries such as: IEC 61508, ISO 26262, and DO 178.

## Detailed

In general these coding guidelines will be a set of rules of do / do not do with examples which should cover all "general" aspects of the Rust programming language, e.g. enums, structs, traits, and so on. We will use the [FLS](https://rust-lang.github.io/fls/index.html) as a means to ensure we have a reasonable coverage of the language.

There will be an addendum which covers how various safety standards like ISO 26262 map onto the coding guidelines.

## Criteria

* We produce coding guidelines that make a "best effort" attempt at cataloging common pieces (e.g. functions, arithmetic, unsafe) of the Rust programming language and how they fit into a safety-critical project
  * We will use [MISRA Compliance: 2020](https://misra.org.uk/app/uploads/2021/06/MISRA-Compliance-2020.pdf) for categorization purposes: Mandatory, Required, Advisory, Disapplied. See section 5 of MISRA Compliance: 2020 for more details.
  * We include a rationale with links to parts of the Rust Project and wider Rust community for guidance
  * We will include linkage where appropriate to to various standards, e.g. CERT C, MISRA C, DO 178, ISO 26262
  * We will include practical recommendations on how to use this piece of the language using compliant and non-compliant examples
* We will develop an addendum matrix to 1. clarify which safety standards are supported 2. lower burden of users
  * We will begin with DO 178 and ISO 26262
  * We will begin perhaps chapter level, maybe subsection level _for now_ and may expand granularity of matrix mapping later
* We will release the coding guidelines tagged with the versions of stable Rust that they support (e.g. `1.42`)
* We will find or create Clippy lints which will cover decidable guidelines

### Criteria obtained by discussion with Tooling Subcommittee

* We will affix a label for each guideline, which describes whether said guideline is decidable or not (in the [theory of computation sense](https://en.wikipedia.org/wiki/Decidability_(logic)))
* We will include for each guideline a minimum of one compliant and one non-compliant example of code, to help illustrate its exact meaning and context.
* We will consider only the language reference / spec, not the tooling availability when writing the coding guidelines
* We aim to produce evidence-based guidelines, with statistics around human error when programming Rust, to support:
  1. What guidelines are written, and 
  2. Why a specific suggestion was made
* We will produce the guidelines and a hash of their contents in a machine readable and consistent format, to make consumption simpler for tool vendors. These artifacts are:
  * a `needs.json` containing the contents of the coding guidelines
  * a `guidelines-ids.json` which has hashes of the guidelines' contents, which can be used to check against (and break) a tool vendor's build, until an audit is performed

# Explicit non-goals

* For the initial version to have complete coverage of the Rust programming language
  * "Something" shipped to alleviate pressure at organizations is better than "nothing is available"
  * An accepted means of delivering partially complete coding guidelines by IEC 61508 and other
    similar safety standards is to subset the language.
    * Language subsetting as defined in IEC 61508 and ISO 26262 may be used to prevent the usage
      of certain language constructs which are not suitable for use in safety-critical systems.
    * The same mechanism can be used to subset out portions of the Rust programming language for
      which we do not yet have a sufficient degree of coverage via the coding guidelines.
    * For a more detailed treatment, please see IEC 61508:2010-7, Annex C: "C.2.6.2 Coding standards"
      for a breakdown in a table and "C.4.2 Language subsets" for rationale.
      * A commented version of IEC 61508 is available [here](https://share.ansi.org/Shared%20Documents/News%20and%20Publications/Other%20Documents/IEC%2061508%20Commented%20Version.pdf) from ANSI.
* For any version to be conflict-free with various members' or their organizations' viewpoints
  * Members and their organizations may take different stances on how The Rust Programming Language's constructs should be viewed and approached. This is **okay and expected**.
  * We'd like to ship something that we can obtain broad consensus on.
  * Worst case scenario: there may be a section here or there which a user may need to adjust in an internal version, which would then be downstreamed.
