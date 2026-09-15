class QuantPipelineError(Exception): pass
class ConfigurationError(QuantPipelineError): pass
class CausalityViolation(QuantPipelineError): pass
class SealedDataViolation(QuantPipelineError): pass
class ArtifactValidationError(QuantPipelineError): pass
class NumericalParityError(QuantPipelineError): pass

